"""
gui/views/stock_view.py
~~~~~~~~~~~~~~~~~~~~~~~
Vue gestion des stocks.
"""
from __future__ import annotations
import os
import sys
import csv
import json
import hashlib
import sqlite3
import threading
import webbrowser
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import customtkinter as ctk
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import messagebox, filedialog, ttk

try:
    from tkcalendar import DateEntry
    HAS_TKCALENDAR = True
except ImportError:
    HAS_TKCALENDAR = False
    DateEntry = None

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates

from reportlab.lib              import colors as rl_colors
from reportlab.lib.pagesizes    import A4, landscape
from reportlab.platypus         import (SimpleDocTemplate, Table, TableStyle,
                                        Paragraph, Spacer, Image as RLImage)
from reportlab.lib.styles       import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units        import inch, mm
from reportlab.pdfbase          import pdfmetrics
from reportlab.pdfbase.ttfonts  import TTFont

from config      import AtlasConfig
from database    import AtlasDatabase
from core.stock          import StockEngine
from core.invoice_payment import InvoiceEngine, PaymentEngine
from core.metrics         import BusinessMetricsEngine
from core.analytics       import AtlasTimeSeriesAnalyzer
from core.intelligence    import AtlasIntelligenceEngine, AtlasNarrativeEngine

class AtlasStockView(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, fg_color=AtlasConfig.COLORS["bg"], **kwargs)
        self.app = app

        self.canvas = tk.Canvas(self, highlightthickness=0, bg=AtlasConfig.COLORS["bg"])
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ctk.CTkFrame(self.canvas, fg_color="transparent")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.create_widgets()
        self.load_products()

    def create_widgets(self):
        toolbar = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(toolbar, text="Gestion des stocks", font=ctk.CTkFont(size=20, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(side="left")

        if self.app.current_user['role'] in ['admin', 'manager', 'stock_manager']:
            btn_add = ctk.CTkButton(toolbar, text="+ Nouveau produit", command=self.add_product_dialog, fg_color=AtlasConfig.COLORS["primary"], hover_color="#e06712")
            btn_add.pack(side="right", padx=5)
            btn_mvt = ctk.CTkButton(toolbar, text="Mouvement", command=self.movement_dialog, fg_color=AtlasConfig.COLORS["secondary"])
            btn_mvt.pack(side="right", padx=5)
            btn_edit = ctk.CTkButton(toolbar, text="Modifier", command=self.edit_selected_product, fg_color=AtlasConfig.COLORS["secondary"])
            btn_edit.pack(side="right", padx=5)
            btn_perf = ctk.CTkButton(toolbar, text="Performance", command=self.show_performance, fg_color=AtlasConfig.COLORS["warning"], text_color="black")
            btn_perf.pack(side="right", padx=5)

        filter_frame = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        filter_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(filter_frame, text="Rechercher:").pack(side="left", padx=10)
        self.search_entry = ctk.CTkEntry(filter_frame, placeholder_text="Nom ou code")
        self.search_entry.pack(side="left", padx=10, fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", lambda e: self.load_products())

        self.tree_frame = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        self.tree_frame.pack(fill="both", expand=True, padx=20, pady=10)

        columns = ("ID", "Code", "Nom", "Catégorie", "Stock", "Min", "Prix", "Actif", "Score")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c))
            self.tree.column(col, width=100 if col!="Nom" else 150)

        scrollbar_tree = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_tree.set)
        scrollbar_tree.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<Double-1>", self.edit_product_dialog)

    def sort_treeview(self, col):
        data = [(self.tree.set(child, col), child) for child in self.tree.get_children('')]
        data.sort()
        for index, (val, child) in enumerate(data):
            self.tree.move(child, '', index)

    def load_products(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        search = self.search_entry.get()
        if search:
            query = "SELECT * FROM products WHERE name LIKE ? OR code LIKE ? ORDER BY name"
            params = (f'%{search}%', f'%{search}%')
        else:
            query = "SELECT * FROM products ORDER BY name"
            params = ()

        products = self.app.db.fetch_all(query, params)
        for p in products:
            score = self.app.stock_engine.product_performance_score(p['id'])
            self.tree.insert("", "end", iid=p['id'], values=(
                p['id'], p['code'], p['name'], p['category'], p['current_stock'],
                p['min_stock'], f"{p['unit_price']} {AtlasConfig.settings['currency']}",
                "Oui" if p['active'] else "Non", f"{score:.0f}"
            ))

    def show_performance(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Sélection", "Veuillez sélectionner un produit")
            return
        product_id = int(selected[0])
        prod = self.app.db.fetch_one("SELECT * FROM products WHERE id=?", (product_id,))
        if not prod:
            return
        score = self.app.stock_engine.product_performance_score(product_id)
        rec = self.app.intelligence_engine.smart_restock_recommendation(product_id)

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Performance - {prod['name']}")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text=f"Score de performance: {score:.0f}/100", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        ctk.CTkLabel(dialog, text=rec, wraplength=350, justify="left").pack(pady=10)

        ctk.CTkLabel(dialog, text="Simulation de réapprovisionnement:").pack(pady=5)
        sim_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        sim_frame.pack(pady=5)
        ctk.CTkLabel(sim_frame, text="Quantité:").pack(side="left", padx=5)
        qty_var = tk.IntVar(value=10)
        qty_spin = ctk.CTkEntry(sim_frame, textvariable=qty_var, width=60)
        qty_spin.pack(side="left", padx=5)

        def run_sim():
            sim = self.app.stock_engine.restock_simulation(product_id, qty_var.get())
            msg = f"Profit attendu: {sim.get('expected_profit',0):.2f}{AtlasConfig.settings['currency']}\nCoût stockage: {sim.get('storage_cost',0):.2f}{AtlasConfig.settings['currency']}\nGain net: {sim.get('net_gain',0):.2f}{AtlasConfig.settings['currency']}"
            messagebox.showinfo("Simulation", msg)

        ctk.CTkButton(dialog, text="Simuler", command=run_sim, fg_color=AtlasConfig.COLORS["primary"]).pack(pady=10)

    def add_product_dialog(self):
        if self.app.current_user['role'] not in ['admin', 'manager', 'stock_manager']:
            messagebox.showerror("Permission", "Vous n'avez pas les droits pour ajouter un produit.")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Nouveau produit")
        dialog.geometry("500x600")
        dialog.transient(self)
        dialog.grab_set()

        fields = [
            ("Code", "code"),
            ("Nom", "name"),
            ("Description", "description"),
            ("Catégorie", "category"),
            ("Prix unitaire", "unit_price"),
            ("Prix d'achat", "cost_price"),
            ("Stock initial", "current_stock"),
            ("Stock minimum", "min_stock"),
            ("Stock maximum", "max_stock"),
            ("Emplacement", "location")
        ]
        entries = {}
        row = 0
        for label, key in fields:
            ctk.CTkLabel(dialog, text=label).grid(row=row, column=0, padx=10, pady=5, sticky="e")
            entry = ctk.CTkEntry(dialog)
            entry.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
            entries[key] = entry
            row += 1

        active_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(dialog, text="Actif", variable=active_var).grid(row=row, column=0, columnspan=2, pady=10)

        def save():
            try:
                code = entries['code'].get().strip()
                if not code:
                    name = entries['name'].get().strip()
                    code = name[:10].upper().replace(" ", "_")
                if not code or not entries['name'].get():
                    messagebox.showerror("Erreur", "Le code et le nom sont obligatoires")
                    return

                self.app.db.execute("""
                    INSERT INTO products (code, name, description, category, unit_price, cost_price,
                                         current_stock, min_stock, max_stock, location, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    code,
                    entries['name'].get(),
                    entries['description'].get(),
                    entries['category'].get(),
                    float(entries['unit_price'].get() or 0),
                    float(entries['cost_price'].get() or 0),
                    int(entries['current_stock'].get() or 0),
                    int(entries['min_stock'].get() or 0),
                    int(entries['max_stock'].get()) if entries['max_stock'].get() else None,
                    entries['location'].get(),
                    1 if active_var.get() else 0
                ))
                self.app.db.commit()
                self.app.log_action("product_created", f"Produit {code}")
                dialog.destroy()
                self.load_products()
            except Exception as e:
                messagebox.showerror("Erreur", str(e))

        btn_save = ctk.CTkButton(dialog, text="Enregistrer", command=save, fg_color=AtlasConfig.COLORS["primary"])
        btn_save.grid(row=row+1, column=0, columnspan=2, pady=20)

    def edit_selected_product(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Sélection", "Veuillez sélectionner un produit")
            return
        self.edit_product_dialog(None)

    def edit_product_dialog(self, event):
        if self.app.current_user['role'] not in ['admin', 'manager', 'stock_manager']:
            messagebox.showerror("Permission", "Vous n'avez pas les droits pour modifier un produit.")
            return
        selected = self.tree.selection()
        if not selected:
            return
        product_id = selected[0]
        product = dict(self.app.db.fetch_one("SELECT * FROM products WHERE id = ?", (product_id,)))
        if not product:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Modifier produit")
        dialog.geometry("500x600")
        dialog.transient(self)
        dialog.grab_set()

        fields = [
            ("Code", "code"),
            ("Nom", "name"),
            ("Description", "description"),
            ("Catégorie", "category"),
            ("Prix unitaire", "unit_price"),
            ("Prix d'achat", "cost_price"),
            ("Stock minimum", "min_stock"),
            ("Stock maximum", "max_stock"),
            ("Emplacement", "location")
        ]
        entries = {}
        row = 0
        for label, key in fields:
            ctk.CTkLabel(dialog, text=label).grid(row=row, column=0, padx=10, pady=5, sticky="e")
            entry = ctk.CTkEntry(dialog)
            entry.insert(0, str(product.get(key, "")))
            entry.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
            entries[key] = entry
            row += 1

        ctk.CTkLabel(dialog, text="Stock actuel").grid(row=row, column=0, padx=10, pady=5, sticky="e")
        stock_label = ctk.CTkLabel(dialog, text=str(product['current_stock']))
        stock_label.grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        active_var = tk.BooleanVar(value=product['active'])
        ctk.CTkCheckBox(dialog, text="Actif", variable=active_var).grid(row=row, column=0, columnspan=2, pady=10)

        def save():
            try:
                self.app.db.execute("""
                    UPDATE products SET code=?, name=?, description=?, category=?, unit_price=?, cost_price=?,
                        min_stock=?, max_stock=?, location=?, active=?
                    WHERE id=?
                """, (
                    entries['code'].get(),
                    entries['name'].get(),
                    entries['description'].get(),
                    entries['category'].get(),
                    float(entries['unit_price'].get() or 0),
                    float(entries['cost_price'].get() or 0),
                    int(entries['min_stock'].get() or 0),
                    int(entries['max_stock'].get()) if entries['max_stock'].get() else None,
                    entries['location'].get(),
                    1 if active_var.get() else 0,
                    product_id
                ))
                self.app.db.commit()
                self.app.log_action("product_updated", f"Produit {product_id}")
                dialog.destroy()
                self.load_products()
            except Exception as e:
                messagebox.showerror("Erreur", str(e))

        btn_save = ctk.CTkButton(dialog, text="Enregistrer", command=save, fg_color=AtlasConfig.COLORS["primary"])
        btn_save.grid(row=row+1, column=0, columnspan=2, pady=20)

    def movement_dialog(self):
        if self.app.current_user['role'] not in ['admin', 'manager', 'stock_manager']:
            messagebox.showerror("Permission", "Vous n'avez pas les droits pour effectuer un mouvement.")
            return
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Sélection", "Veuillez sélectionner un produit")
            return
        product_id = selected[0]
        product = dict(self.app.db.fetch_one("SELECT * FROM products WHERE id = ?", (product_id,)))
        if not product:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Mouvement pour {product['name']}")
        dialog.geometry("400x400")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Type de mouvement:").pack(pady=5)
        type_var = tk.StringVar(value="Entrée")
        type_menu = ctk.CTkOptionMenu(dialog, values=["Entrée", "Sortie", "Ajustement"], variable=type_var)
        type_menu.pack(pady=5)

        ctk.CTkLabel(dialog, text="Quantité:").pack(pady=5)
        qty_entry = ctk.CTkEntry(dialog)
        qty_entry.pack(pady=5)

        ctk.CTkLabel(dialog, text="Prix unitaire (optionnel):").pack(pady=5)
        price_entry = ctk.CTkEntry(dialog)
        price_entry.pack(pady=5)

        ctk.CTkLabel(dialog, text="Référence (ex: bon de commande):").pack(pady=5)
        ref_entry = ctk.CTkEntry(dialog)
        ref_entry.pack(pady=5)

        ctk.CTkLabel(dialog, text="Raison:").pack(pady=5)
        reason_entry = ctk.CTkEntry(dialog)
        reason_entry.pack(pady=5)

        def save():
            try:
                qty = int(qty_entry.get())
                mvt_type = type_var.get().lower()
                if mvt_type == "entrée":
                    mvt_type = "in"
                elif mvt_type == "sortie":
                    mvt_type = "out"
                else:
                    mvt_type = "adjustment"

                price = price_entry.get()
                unit_price = float(price) if price else None

                self.app.stock_engine.add_movement(
                    product_id=int(product_id),
                    movement_type=mvt_type,
                    quantity=qty,
                    unit_price=unit_price,
                    reason=reason_entry.get(),
                    reference=ref_entry.get(),
                    user_id=self.app.current_user['id']
                )
                dialog.destroy()
                self.load_products()
            except Exception as e:
                messagebox.showerror("Erreur", str(e))

        ctk.CTkButton(dialog, text="Valider", command=save, fg_color=AtlasConfig.COLORS["primary"]).pack(pady=20)

# ========================
# FINANCE VIEW (avec scrollbar)
# ========================
