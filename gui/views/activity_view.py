"""
gui/views/activity_view.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Vue journal d'activité.
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

class AtlasActivityLogView(ctk.CTkFrame):
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
        self.load_logs()

    def create_widgets(self):
        title = ctk.CTkLabel(self.scrollable_frame, text="Journal d'activité", font=ctk.CTkFont(size=24, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"])
        title.pack(pady=10, padx=20, anchor="w")

        filter_frame = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        filter_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(filter_frame, text="Filtrer par utilisateur:").pack(side="left", padx=10)
        users = self.app.db.fetch_all("SELECT id, username FROM users ORDER BY username")
        user_list = ["Tous"] + [f"{u['id']} - {u['username']}" for u in users]
        self.user_filter = tk.StringVar(value="Tous")
        user_menu = ctk.CTkOptionMenu(filter_frame, values=user_list, variable=self.user_filter, command=lambda x: self.load_logs())
        user_menu.pack(side="left", padx=10)

        ctk.CTkLabel(filter_frame, text="Période (jours):").pack(side="left", padx=10)
        self.days_filter = ctk.CTkEntry(filter_frame, width=50)
        self.days_filter.insert(0, "30")
        self.days_filter.pack(side="left", padx=10)
        btn_refresh = ctk.CTkButton(filter_frame, text="Rafraîchir", command=self.load_logs, fg_color=AtlasConfig.COLORS["primary"])
        btn_refresh.pack(side="left", padx=10)

        self.tree_frame = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        self.tree_frame.pack(fill="both", expand=True, padx=20, pady=10)

        columns = ("ID", "Utilisateur", "Action", "Détails", "IP", "Date/Heure")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", height=20)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150 if col == "Détails" else 100)

        scrollbar_tree = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_tree.set)
        scrollbar_tree.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

    def load_logs(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        days = self.days_filter.get()
        try:
            days = int(days)
        except:
            days = 30

        params = []
        query = """
            SELECT al.*, u.username 
            FROM activity_log al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE al.created_at >= datetime('now', ?)
        """
        params.append(f'-{days} days')

        user_filter = self.user_filter.get()
        if user_filter != "Tous":
            user_id = int(user_filter.split(" - ")[0])
            query += " AND al.user_id = ?"
            params.append(user_id)

        query += " ORDER BY al.created_at DESC LIMIT 1000"

        logs = self.app.db.fetch_all(query, tuple(params))
        for log in logs:
            self.tree.insert("", "end", values=(
                log['id'],
                log['username'] or "Inconnu",
                log['action'],
                log['details'] or "",
                log['ip_address'] or "",
                log['created_at']
            ))

# ========================
# SETTINGS VIEW (avec scrollbar déjà intégrée)
# ========================
