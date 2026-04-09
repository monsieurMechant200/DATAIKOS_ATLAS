"""
gui/login.py
~~~~~~~~~~~~
Fenêtre de connexion.
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

class LoginWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.title("Connexion - Dataikos Atlas")
        self.geometry("400x300")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()

        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (400 // 2)
        y = (self.winfo_screenheight() // 2) - (300 // 2)
        self.geometry(f"+{x}+{y}")

        self.create_widgets()

    def create_widgets(self):
        frame = ctk.CTkFrame(self, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        frame.pack(expand=True, fill="both", padx=20, pady=20)

        ctk.CTkLabel(frame, text="Connexion à Dataikos Atlas", font=ctk.CTkFont(size=18, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(pady=20)

        ctk.CTkLabel(frame, text="Nom d'utilisateur:").pack(pady=(10,0))
        self.username_entry = ctk.CTkEntry(frame, width=200)
        self.username_entry.pack(pady=5)

        ctk.CTkLabel(frame, text="Mot de passe:").pack(pady=(10,0))
        self.password_entry = ctk.CTkEntry(frame, width=200, show="*")
        self.password_entry.pack(pady=5)

        btn_login = ctk.CTkButton(frame, text="Se connecter", command=self.login, fg_color=AtlasConfig.COLORS["primary"])
        btn_login.pack(pady=20)

        self.username_entry.focus()
        self.bind("<Return>", lambda e: self.login())

    def login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()
        password_hash = hashlib.sha256(password.encode()).hexdigest()

        user = self.app.db.fetch_one(
            "SELECT id, username, full_name, role, active FROM users WHERE username = ? AND password_hash = ?",
            (username, password_hash)
        )
        if user and user['active']:
            self.app.current_user = dict(user)
            self.app.db.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
            self.app.db.commit()
            self.destroy()
        else:
            messagebox.showerror("Erreur", "Identifiants incorrects ou compte désactivé")

# ========================
# USER MANAGEMENT VIEW (avec scrollbar)
# ========================
