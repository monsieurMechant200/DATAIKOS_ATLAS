"""
gui/views/users_view.py
~~~~~~~~~~~~~~~~~~~~~~~
Vue gestion des utilisateurs.
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

class AtlasUserManagementView(ctk.CTkFrame):
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
        self.load_users()

    def create_widgets(self):
        title = ctk.CTkLabel(self.scrollable_frame, text="Gestion des utilisateurs", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=10, padx=20, anchor="w")

        toolbar = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=5)

        btn_add = ctk.CTkButton(toolbar, text="+ Nouvel utilisateur", command=self.add_user_dialog, fg_color=AtlasConfig.COLORS["primary"])
        btn_add.pack(side="left", padx=5)

        self.tree_frame = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        self.tree_frame.pack(fill="both", expand=True, padx=20, pady=10)

        columns = ("ID", "Nom d'utilisateur", "Nom complet", "Email", "Rôle", "Actif", "Dernière connexion")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c))
            self.tree.column(col, width=120)

        scrollbar_tree = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_tree.set)
        scrollbar_tree.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<Double-1>", self.edit_user_dialog)

    def sort_treeview(self, col):
        data = [(self.tree.set(child, col), child) for child in self.tree.get_children('')]
        data.sort()
        for index, (val, child) in enumerate(data):
            self.tree.move(child, '', index)

    def load_users(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        users = self.app.db.fetch_all("SELECT id, username, full_name, email, role, active, last_login FROM users ORDER BY username")
        for u in users:
            self.tree.insert("", "end", iid=u['id'], values=(
                u['id'],
                u['username'],
                u['full_name'] or "",
                u['email'] or "",
                u['role'],
                "Oui" if u['active'] else "Non",
                u['last_login'] or ""
            ))

    def add_user_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Nouvel utilisateur")
        dialog.geometry("400x500")
        dialog.transient(self)
        dialog.grab_set()

        fields = [
            ("Nom d'utilisateur", "username"),
            ("Mot de passe", "password"),
            ("Nom complet", "full_name"),
            ("Email", "email"),
            ("Rôle", "role")
        ]
        entries = {}
        row = 0
        for label, key in fields:
            ctk.CTkLabel(dialog, text=label).grid(row=row, column=0, padx=10, pady=5, sticky="e")
            if key == "role":
                entry = ctk.CTkOptionMenu(dialog, values=["admin", "manager", "commercial", "stock_manager"])
                entry.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
            elif key == "password":
                entry = ctk.CTkEntry(dialog, show="*")
                entry.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
            else:
                entry = ctk.CTkEntry(dialog)
                entry.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
            entries[key] = entry
            row += 1

        active_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(dialog, text="Actif", variable=active_var).grid(row=row, column=0, columnspan=2, pady=10)

        def save():
            try:
                username = entries['username'].get().strip()
                password = entries['password'].get().strip()
                if not username or not password:
                    messagebox.showerror("Erreur", "Nom d'utilisateur et mot de passe obligatoires")
                    return
                password_hash = hashlib.sha256(password.encode()).hexdigest()
                role = entries['role'].get()
                self.app.db.execute("""
                    INSERT INTO users (username, password_hash, full_name, email, role, active)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    username,
                    password_hash,
                    entries['full_name'].get(),
                    entries['email'].get(),
                    role,
                    1 if active_var.get() else 0
                ))
                self.app.db.commit()
                self.app.log_action("user_created", f"Utilisateur {username}")
                dialog.destroy()
                self.load_users()
            except sqlite3.IntegrityError:
                messagebox.showerror("Erreur", "Ce nom d'utilisateur existe déjà")
            except Exception as e:
                messagebox.showerror("Erreur", str(e))

        btn_save = ctk.CTkButton(dialog, text="Créer", command=save, fg_color=AtlasConfig.COLORS["primary"])
        btn_save.grid(row=row+1, column=0, columnspan=2, pady=20)

    def edit_user_dialog(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        user_id = selected[0]
        user = dict(self.app.db.fetch_one("SELECT id, username, full_name, email, role, active FROM users WHERE id = ?", (user_id,)))
        if not user:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Modifier utilisateur")
        dialog.geometry("400x500")
        dialog.transient(self)
        dialog.grab_set()

        row = 0
        ctk.CTkLabel(dialog, text="Nom d'utilisateur").grid(row=row, column=0, padx=10, pady=5, sticky="e")
        username_label = ctk.CTkLabel(dialog, text=user['username'])
        username_label.grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        ctk.CTkLabel(dialog, text="Nouveau mot de passe").grid(row=row, column=0, padx=10, pady=5, sticky="e")
        password_entry = ctk.CTkEntry(dialog, show="*")
        password_entry.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
        row += 1

        ctk.CTkLabel(dialog, text="Nom complet").grid(row=row, column=0, padx=10, pady=5, sticky="e")
        fullname_entry = ctk.CTkEntry(dialog)
        fullname_entry.insert(0, user['full_name'] or "")
        fullname_entry.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
        row += 1

        ctk.CTkLabel(dialog, text="Email").grid(row=row, column=0, padx=10, pady=5, sticky="e")
        email_entry = ctk.CTkEntry(dialog)
        email_entry.insert(0, user['email'] or "")
        email_entry.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
        row += 1

        ctk.CTkLabel(dialog, text="Rôle").grid(row=row, column=0, padx=10, pady=5, sticky="e")
        role_var = tk.StringVar(value=user['role'])
        role_menu = ctk.CTkOptionMenu(dialog, values=["admin", "manager", "commercial", "stock_manager"], variable=role_var)
        role_menu.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
        row += 1

        active_var = tk.BooleanVar(value=user['active'])
        ctk.CTkCheckBox(dialog, text="Actif", variable=active_var).grid(row=row, column=0, columnspan=2, pady=10)
        row += 1

        def save():
            try:
                if password_entry.get():
                    pwd_hash = hashlib.sha256(password_entry.get().encode()).hexdigest()
                    self.app.db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_hash, user_id))

                self.app.db.execute("""
                    UPDATE users SET full_name = ?, email = ?, role = ?, active = ? WHERE id = ?
                """, (
                    fullname_entry.get(),
                    email_entry.get(),
                    role_var.get(),
                    1 if active_var.get() else 0,
                    user_id
                ))
                self.app.db.commit()
                self.app.log_action("user_updated", f"Utilisateur {user['username']}")
                dialog.destroy()
                self.load_users()
            except Exception as e:
                messagebox.showerror("Erreur", str(e))

        btn_save = ctk.CTkButton(dialog, text="Enregistrer", command=save, fg_color=AtlasConfig.COLORS["primary"])
        btn_save.grid(row=row, column=0, columnspan=2, pady=20)

# ========================
# CUSTOMER VIEW (avec scrollbar)
# ========================
