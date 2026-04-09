"""
gui/views/customer_view.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Vue gestion des clients.
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

class AtlasCustomerView(ctk.CTkFrame):
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
        self.load_customers()

    def create_widgets(self):
        toolbar = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(toolbar, text="Gestion des clients", font=ctk.CTkFont(size=20, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(side="left")

        if self.app.current_user['role'] in ['admin', 'manager', 'commercial']:
            btn_add = ctk.CTkButton(toolbar, text="+ Nouveau client", command=self.add_customer_dialog, fg_color=AtlasConfig.COLORS["primary"])
            btn_add.pack(side="right", padx=5)
            btn_edit = ctk.CTkButton(toolbar, text="Modifier", command=self.edit_selected_customer, fg_color=AtlasConfig.COLORS["secondary"])
            btn_edit.pack(side="right", padx=5)

        filter_frame = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        filter_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(filter_frame, text="Rechercher:").pack(side="left", padx=10)
        self.search_entry = ctk.CTkEntry(filter_frame, placeholder_text="Nom ou code")
        self.search_entry.pack(side="left", padx=10, fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", lambda e: self.load_customers())

        self.tree_frame = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        self.tree_frame.pack(fill="both", expand=True, padx=20, pady=10)

        columns = ("ID", "Code", "Nom", "Email", "Téléphone", "Ville", "Actif")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c))
            self.tree.column(col, width=100)

        scrollbar_tree = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_tree.set)
        scrollbar_tree.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<Double-1>", self.edit_customer_dialog)

    def sort_treeview(self, col):
        data = [(self.tree.set(child, col), child) for child in self.tree.get_children('')]
        data.sort()
        for index, (val, child) in enumerate(data):
            self.tree.move(child, '', index)

    def load_customers(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        search = self.search_entry.get()
        if search:
            query = "SELECT * FROM customers WHERE name LIKE ? OR code LIKE ? ORDER BY name"
            params = (f'%{search}%', f'%{search}%')
        else:
            query = "SELECT * FROM customers ORDER BY name"
            params = ()

        customers = self.app.db.fetch_all(query, params)
        for c in customers:
            self.tree.insert("", "end", iid=c['id'], values=(
                c['id'], c['code'], c['name'], c['email'], c['phone'], c['city'],
                "Oui" if c['active'] else "Non"
            ))

    def add_customer_dialog(self):
        if self.app.current_user['role'] not in ['admin', 'manager', 'commercial']:
            messagebox.showerror("Permission", "Vous n'avez pas les droits pour ajouter un client.")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Nouveau client")
        dialog.geometry("500x600")
        dialog.transient(self)
        dialog.grab_set()

        fields = [
            ("Code", "code"),
            ("Nom", "name"),
            ("Email", "email"),
            ("Téléphone", "phone"),
            ("Adresse", "address"),
            ("Ville", "city"),
            ("Code postal", "postal_code"),
            ("Pays", "country"),
            ("N° TVA", "tax_id"),
            ("Délais paiement", "payment_terms"),
            ("Limite crédit", "credit_limit")
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
                    INSERT INTO customers (code, name, email, phone, address, city, postal_code, country,
                                          tax_id, payment_terms, credit_limit, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    code,
                    entries['name'].get(),
                    entries['email'].get(),
                    entries['phone'].get(),
                    entries['address'].get(),
                    entries['city'].get(),
                    entries['postal_code'].get(),
                    entries['country'].get(),
                    entries['tax_id'].get(),
                    int(entries['payment_terms'].get() or 30),
                    float(entries['credit_limit'].get() or 0),
                    1 if active_var.get() else 0
                ))
                self.app.db.commit()
                self.app.log_action("customer_created", f"Client {code}")
                dialog.destroy()
                self.load_customers()
            except Exception as e:
                messagebox.showerror("Erreur", str(e))

        btn_save = ctk.CTkButton(dialog, text="Enregistrer", command=save, fg_color=AtlasConfig.COLORS["primary"])
        btn_save.grid(row=row+1, column=0, columnspan=2, pady=20)

    def edit_selected_customer(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Sélection", "Veuillez sélectionner un client")
            return
        self.edit_customer_dialog(None)

    def edit_customer_dialog(self, event):
        if self.app.current_user['role'] not in ['admin', 'manager', 'commercial']:
            messagebox.showerror("Permission", "Vous n'avez pas les droits pour modifier un client.")
            return
        selected = self.tree.selection()
        if not selected:
            return
        customer_id = selected[0]
        customer = dict(self.app.db.fetch_one("SELECT * FROM customers WHERE id = ?", (customer_id,)))
        if not customer:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Modifier client")
        dialog.geometry("500x600")
        dialog.transient(self)
        dialog.grab_set()

        fields = [
            ("Code", "code"),
            ("Nom", "name"),
            ("Email", "email"),
            ("Téléphone", "phone"),
            ("Adresse", "address"),
            ("Ville", "city"),
            ("Code postal", "postal_code"),
            ("Pays", "country"),
            ("N° TVA", "tax_id"),
            ("Délais paiement", "payment_terms"),
            ("Limite crédit", "credit_limit")
        ]
        entries = {}
        row = 0
        for label, key in fields:
            ctk.CTkLabel(dialog, text=label).grid(row=row, column=0, padx=10, pady=5, sticky="e")
            entry = ctk.CTkEntry(dialog)
            entry.insert(0, str(customer.get(key, "")))
            entry.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
            entries[key] = entry
            row += 1

        active_var = tk.BooleanVar(value=customer['active'])
        ctk.CTkCheckBox(dialog, text="Actif", variable=active_var).grid(row=row, column=0, columnspan=2, pady=10)

        def save():
            try:
                code = entries['code'].get().strip()
                if not code:
                    messagebox.showerror("Erreur", "Le code est obligatoire")
                    return
                self.app.db.execute("""
                    UPDATE customers SET code=?, name=?, email=?, phone=?, address=?, city=?,
                        postal_code=?, country=?, tax_id=?, payment_terms=?, credit_limit=?, active=?
                    WHERE id=?
                """, (
                    code,
                    entries['name'].get(),
                    entries['email'].get(),
                    entries['phone'].get(),
                    entries['address'].get(),
                    entries['city'].get(),
                    entries['postal_code'].get(),
                    entries['country'].get(),
                    entries['tax_id'].get(),
                    int(entries['payment_terms'].get() or 30),
                    float(entries['credit_limit'].get() or 0),
                    1 if active_var.get() else 0,
                    customer_id
                ))
                self.app.db.commit()
                self.app.log_action("customer_updated", f"Client {customer_id}")
                dialog.destroy()
                self.load_customers()
            except Exception as e:
                messagebox.showerror("Erreur", str(e))

        btn_save = ctk.CTkButton(dialog, text="Enregistrer", command=save, fg_color=AtlasConfig.COLORS["primary"])
        btn_save.grid(row=row+1, column=0, columnspan=2, pady=20)

# ========================
# UNIT TESTS (inchangés)
# ========================
