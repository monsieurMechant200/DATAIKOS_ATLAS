"""
gui/sidebar.py
~~~~~~~~~~~~~~
Barre de navigation latérale.
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

class AtlasSidebar(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=AtlasConfig.COLORS["sidebar"], width=200, **kwargs)
        self.pack_propagate(False)
        self.create_widgets()

    def create_widgets(self):
        logo_label = ctk.CTkLabel(self, text="🗺️ ATLAS", 
                                   font=ctk.CTkFont(size=20, weight="bold"),
                                   text_color=AtlasConfig.COLORS["text_light"])
        logo_label.pack(pady=20)

        nav_items = [
            ("📊 Command Center", "dashboard"),
            ("📦 Stock", "stock"),
            ("💰 Finance", "invoices"),
            ("👥 Clients", "customers"),
            ("📈 Analytics", "analytics"),
        ]
        if self.master.current_user['role'] == 'admin':
            nav_items.append(("📋 Activité", "activity_log"))
            nav_items.append(("👤 Utilisateurs", "users"))

        nav_items.append(("⚙️ Paramètres", "settings"))

        for text, view in nav_items:
            btn = ctk.CTkButton(self, text=text, 
                                fg_color="transparent", 
                                anchor="w",
                                hover_color=AtlasConfig.COLORS["primary"],
                                command=lambda v=view: self.master.show_view(v))
            btn.pack(fill="x", padx=10, pady=5)

        user_label = ctk.CTkLabel(self, text=f"👤 {self.master.current_user['username']} ({self.master.current_user['role']})",
                                  text_color=AtlasConfig.COLORS["text_light"], font=ctk.CTkFont(size=12))
        user_label.pack(side="bottom", pady=10)

# ========================
# MAIN APPLICATION (inchangée)
# ========================
