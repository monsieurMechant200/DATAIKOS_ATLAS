"""
gui/views/settings_view.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Vue paramètres de l'application.
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

class AtlasSettingsView(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, fg_color=AtlasConfig.COLORS["bg"], **kwargs)
        self.app = app

        # Settings view utilise déjà un canvas interne pour le défilement
        self.create_widgets()

    def create_widgets(self):
        ctk.CTkLabel(self, text="Paramètres", font=ctk.CTkFont(size=24, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(pady=10)

        if self.app.current_user['role'] != 'admin':
            ctk.CTkLabel(self, text="Seul l'administrateur peut modifier les paramètres.", text_color=AtlasConfig.COLORS["danger"]).pack(pady=10)
            return

        canvas = tk.Canvas(self, bg=AtlasConfig.COLORS["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scrollable_frame = ctk.CTkFrame(canvas, fg_color="transparent")

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.entries = {}
        self.logo_path_var = tk.StringVar(value=AtlasConfig.settings.get("logo_path", ""))

        self.create_section_entreprise(scrollable_frame)

        self.create_section(scrollable_frame, "Général", [
            ("Nom de l'entreprise", "company_name"),
            ("Devise", "currency"),
            ("Taux TVA (%)", "vat_rate"),
            ("Format date", "date_format"),
            ("Langue", "language")
        ])

        self.create_section(scrollable_frame, "Stock", [
            ("Seuil alerte global", "stock_alert_threshold"),
            ("Méthode (FIFO/LIFO)", "stock_method"),
            ("Politique réappro", "reorder_policy")
        ])

        self.create_section(scrollable_frame, "Facturation", [
            ("Numérotation auto (True/False)", "invoice_auto_numbering"),
            ("Délais paiement (jours)", "payment_terms"),
            ("Délais rappel", "reminder_delay")
        ])

        self.create_section(scrollable_frame, "Analyse", [
            ("Période saisonnalité", "seasonality_period"),
            ("Horizon forecast (jours)", "forecast_horizon"),
            ("Auto-optimisation (True/False)", "auto_optimization"),
            ("Sélection modèle", "model_selection")
        ])

        self.create_section(scrollable_frame, "Interface", [
            ("Thème (Light/Dark)", "ui_theme"),
            ("Couleur accent", "ui_accent"),
            ("Densité", "ui_density"),
            ("Taille police", "ui_font_size"),
            ("Animations (True/False)", "ui_animations")
        ])

        ctk.CTkButton(scrollable_frame, text="Sauvegarder", command=self.save_settings, fg_color=AtlasConfig.COLORS["primary"]).pack(pady=20)

    def create_section_entreprise(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(frame, text="Informations de l'entreprise", font=ctk.CTkFont(size=16, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(pady=5)

        fields = [
            ("Adresse", "company_address"),
            ("Téléphone", "company_phone"),
            ("Email", "company_email"),
            ("Numéro fiscal", "company_tax_id")
        ]
        for label, key in fields:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=5)
            ctk.CTkLabel(row, text=label, width=150).pack(side="left")
            entry = ctk.CTkEntry(row)
            entry.pack(side="left", fill="x", expand=True)
            entry.insert(0, str(AtlasConfig.settings.get(key, "")))
            self.entries[key] = entry

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(row, text="Logo", width=150).pack(side="left")
        logo_entry = ctk.CTkEntry(row, textvariable=self.logo_path_var, state="readonly")
        logo_entry.pack(side="left", fill="x", expand=True, padx=(0,5))
        btn_browse = ctk.CTkButton(row, text="Parcourir", command=self.browse_logo, width=80)
        btn_browse.pack(side="right")

        self.logo_preview = ctk.CTkLabel(frame, text="", width=100, height=50)
        self.logo_preview.pack(pady=5)
        self.update_logo_preview()

    def browse_logo(self):
        filename = filedialog.askopenfilename(
            title="Sélectionner le logo",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp")]
        )
        if filename:
            dest = os.path.join(AtlasConfig.UPLOADS_DIR, os.path.basename(filename))
            shutil.copy2(filename, dest)
            self.logo_path_var.set(dest)
            self.update_logo_preview()

    def update_logo_preview(self):
        path = self.logo_path_var.get()
        if path and os.path.exists(path):
            try:
                img = Image.open(path)
                img.thumbnail((100, 50))
                photo = ctk.CTkImage(img, size=(100, 50))
                self.logo_preview.configure(image=photo, text="")
            except:
                self.logo_preview.configure(image=None, text="Erreur chargement")
        else:
            self.logo_preview.configure(image=None, text="Aucun logo")

    def create_section(self, parent, title, fields):
        frame = ctk.CTkFrame(parent, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=16, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(pady=5)
        for label, key in fields:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=5)
            ctk.CTkLabel(row, text=label, width=150).pack(side="left")
            entry = ctk.CTkEntry(row)
            entry.pack(side="left", fill="x", expand=True)
            entry.insert(0, str(AtlasConfig.settings.get(key, "")))
            self.entries[key] = entry

    def save_settings(self):
        for key, entry in self.entries.items():
            value = entry.get()
            if key in ["stock_alert_threshold", "payment_terms", "reminder_delay", "seasonality_period", "forecast_horizon", "ui_font_size"]:
                try:
                    value = int(value)
                except:
                    pass
            elif key in ["vat_rate"]:
                try:
                    value = float(value)
                except:
                    pass
            elif key in ["invoice_auto_numbering", "auto_optimization", "ui_animations"]:
                value = value.lower() == "true"
            AtlasConfig.settings[key] = value

        AtlasConfig.settings["logo_path"] = self.logo_path_var.get()

        AtlasConfig.save_settings()
        ctk.set_appearance_mode(AtlasConfig.settings["ui_theme"].lower())
        self.app.log_action("settings_updated", "Paramètres modifiés")
        messagebox.showinfo("Succès", "Paramètres sauvegardés.")

# ========================
# SIDEBAR (inchangée)
# ========================
