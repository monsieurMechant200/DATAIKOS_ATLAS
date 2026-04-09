"""
gui/app.py
~~~~~~~~~~
Fenêtre principale — DataikosAtlasApp.
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

from gui.login   import LoginWindow
from gui.sidebar import AtlasSidebar
from gui.views   import (
    AtlasDashboard, AtlasStockView, AtlasFinanceView,
    AtlasCustomerView, AtlasAnalyticsView, AtlasActivityLogView,
    AtlasUserManagementView, AtlasSettingsView,
)

class DataikosAtlasApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{AtlasConfig.APP_NAME} v{AtlasConfig.APP_VERSION}")
        self.geometry("1400x900")
        self.minsize(1200, 700)

        self.db = AtlasDatabase()
        self.stock_engine = StockEngine(self.db, self)
        self.invoice_engine = InvoiceEngine(self.db, self)
        self.payment_engine = PaymentEngine(self.db, self)
        self.metrics_engine = BusinessMetricsEngine(self.db, self)
        self.intelligence_engine = AtlasIntelligenceEngine(self.db, self)

        self.current_user = None
        self.show_login()

    def show_login(self):
        login = LoginWindow(self)
        self.wait_window(login)
        if self.current_user is None:
            self.destroy()
            return
        self.after(100, self.init_ui)

    def init_ui(self):
        theme = AtlasConfig.settings["ui_theme"].lower()
        ctk.set_appearance_mode(theme)
        ctk.set_default_color_theme("blue")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = AtlasSidebar(self)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        self.view_container = ctk.CTkFrame(self, fg_color=AtlasConfig.COLORS["bg"])
        self.view_container.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.view_container.grid_columnconfigure(0, weight=1)
        self.view_container.grid_rowconfigure(0, weight=1)

        self.views = {}
        self.current_view = None
        self.create_views()

        self.show_view("dashboard")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_views(self):
        self.views["dashboard"] = AtlasDashboard(self.view_container, self)
        self.views["stock"] = AtlasStockView(self.view_container, self)
        self.views["invoices"] = AtlasFinanceView(self.view_container, self)
        self.views["customers"] = AtlasCustomerView(self.view_container, self)
        self.views["analytics"] = AtlasAnalyticsView(self.view_container, self)
        if self.current_user['role'] == 'admin':
            self.views["activity_log"] = AtlasActivityLogView(self.view_container, self)
            self.views["users"] = AtlasUserManagementView(self.view_container, self)
        self.views["settings"] = AtlasSettingsView(self.view_container, self)

    def show_view(self, view_name: str):
        if view_name not in self.views:
            return
        if self.current_view:
            self.views[self.current_view].grid_forget()
        self.views[view_name].grid(row=0, column=0, sticky="nsew")
        self.current_view = view_name

    def log_action(self, action: str, details: str = ""):
        if self.current_user:
            self.db.execute("""
                INSERT INTO activity_log (user_id, action, details, ip_address)
                VALUES (?, ?, ?, ?)
            """, (self.current_user['id'], action, details, "127.0.0.1"))
            self.db.commit()

    def on_closing(self):
        self.db.close()
        self.destroy()

# ========================
# LOGIN WINDOW (inchangé)
# ========================
