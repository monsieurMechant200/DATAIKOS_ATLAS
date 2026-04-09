"""
gui/views/dashboard.py
~~~~~~~~~~~~~~~~~~~~~~
Vue tableau de bord principal.
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

class AtlasDashboard(ctk.CTkFrame):
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
        self.refresh()

    def create_widgets(self):
        title = ctk.CTkLabel(self.scrollable_frame, text="Atlas Command Center", font=ctk.CTkFont(size=28, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"])
        title.pack(pady=15, padx=25, anchor="w")

        self.insight_frame = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        self.insight_frame.pack(fill="x", padx=25, pady=10)
        self.insight_label = ctk.CTkLabel(self.insight_frame, text="", wraplength=1000, justify="left",
                                          font=ctk.CTkFont(size=14), text_color=AtlasConfig.COLORS["text_dark"])
        self.insight_label.pack(padx=20, pady=15)

        self.kpi_frame = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
        self.kpi_frame.pack(fill="x", padx=25, pady=10)
        self.kpi_frame.grid_columnconfigure((0,1,2,3,4), weight=1)

        self.health_kpi = self.create_kpi_card(self.kpi_frame, "Santé entreprise", "0/100", 0, AtlasConfig.COLORS["primary"])
        self.today_kpi = self.create_kpi_card(self.kpi_frame, "CA aujourd'hui", "0 €", 1, AtlasConfig.COLORS["secondary"])
        self.month_kpi = self.create_kpi_card(self.kpi_frame, "CA 30 jours", "0 €", 2, AtlasConfig.COLORS["secondary"])
        self.growth_kpi = self.create_kpi_card(self.kpi_frame, "Croissance", "0%", 3, AtlasConfig.COLORS["warning"])
        self.stress_kpi = self.create_kpi_card(self.kpi_frame, "Stress stock", "0%", 4, AtlasConfig.COLORS["danger"])

        self.charts_frame = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
        self.charts_frame.pack(fill="both", expand=True, padx=25, pady=10)
        self.charts_frame.grid_columnconfigure(0, weight=1)
        self.charts_frame.grid_rowconfigure(0, weight=1)
        self.charts_frame.grid_rowconfigure(1, weight=1)

        self.fig_finance = plt.Figure(figsize=(6, 3), dpi=100)
        self.ax_finance = self.fig_finance.add_subplot(111)
        self.canvas_finance = FigureCanvasTkAgg(self.fig_finance, master=self.charts_frame)
        self.canvas_finance.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        self.fig_stock = plt.Figure(figsize=(6, 3), dpi=100)
        self.ax_stock = self.fig_stock.add_subplot(111)
        self.canvas_stock = FigureCanvasTkAgg(self.fig_stock, master=self.charts_frame)
        self.canvas_stock.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        bottom_frame = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
        bottom_frame.pack(fill="both", expand=True, padx=25, pady=10)
        bottom_frame.grid_columnconfigure((0,1), weight=1)

        left_col = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        left_col.grid_rowconfigure(0, weight=1)
        left_col.grid_rowconfigure(1, weight=1)

        self.top_products_frame = ctk.CTkFrame(left_col, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        self.top_products_frame.grid(row=0, column=0, sticky="nsew", pady=(0,10))
        ctk.CTkLabel(self.top_products_frame, text="Top 5 produits", font=ctk.CTkFont(size=16, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(pady=10)
        self.products_list = ctk.CTkTextbox(self.top_products_frame, height=150, wrap="none", fg_color=AtlasConfig.COLORS["card"], border_width=0)
        self.products_list.pack(fill="both", expand=True, padx=10, pady=10)

        self.top_customers_frame = ctk.CTkFrame(left_col, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        self.top_customers_frame.grid(row=1, column=0, sticky="nsew")
        ctk.CTkLabel(self.top_customers_frame, text="Top 5 clients", font=ctk.CTkFont(size=16, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(pady=10)
        self.customers_list = ctk.CTkTextbox(self.top_customers_frame, height=150, wrap="none", fg_color=AtlasConfig.COLORS["card"], border_width=0)
        self.customers_list.pack(fill="both", expand=True, padx=10, pady=10)

        right_col = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew", padx=(10,0))
        right_col.grid_rowconfigure(0, weight=1)
        right_col.grid_rowconfigure(1, weight=1)

        forecast_frame = ctk.CTkFrame(right_col, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        forecast_frame.grid(row=0, column=0, sticky="nsew", pady=(0,10))
        ctk.CTkLabel(forecast_frame, text="Prévision mois prochain", font=ctk.CTkFont(size=16, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(pady=10)
        self.forecast_label = ctk.CTkLabel(forecast_frame, text="Calcul en cours...", font=ctk.CTkFont(size=24, weight="bold"), text_color=AtlasConfig.COLORS["warning"])
        self.forecast_label.pack(pady=20)

        alerts_frame = ctk.CTkFrame(right_col, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        alerts_frame.grid(row=1, column=0, sticky="nsew")
        ctk.CTkLabel(alerts_frame, text="Alertes critiques", font=ctk.CTkFont(size=16, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(pady=10)
        self.alerts_list = ctk.CTkTextbox(alerts_frame, height=150, wrap="word", fg_color=AtlasConfig.COLORS["card"], border_width=0)
        self.alerts_list.pack(fill="both", expand=True, padx=10, pady=10)

    def create_kpi_card(self, parent, title, value, col, color):
        frame = ctk.CTkFrame(parent, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        frame.grid(row=0, column=col, sticky="nsew", padx=5)
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=12), text_color=AtlasConfig.COLORS["text_muted"]).pack(pady=(10,0))
        label = ctk.CTkLabel(frame, text=value, font=ctk.CTkFont(size=22, weight="bold"), text_color=color)
        label.pack(pady=(0,10))
        return label

    def refresh(self):
        metrics = BusinessMetricsEngine(self.app.db, self.app)
        intelligence = self.app.intelligence_engine
        narrative = AtlasNarrativeEngine(self.app.db, self.app)

        today_ca = metrics.get_today_revenue()
        month_ca = metrics.get_last_30_days_revenue()
        growth = metrics.get_growth_percentage()
        health = metrics.get_business_health_score()
        stress = metrics.get_inventory_stress()

        self.today_kpi.configure(text=f"{today_ca:.2f} {AtlasConfig.settings['currency']}")
        self.month_kpi.configure(text=f"{month_ca:.2f} {AtlasConfig.settings['currency']}")
        self.growth_kpi.configure(text=f"{growth:.1f}%")
        self.health_kpi.configure(text=f"{health}/100")
        self.stress_kpi.configure(text=f"{stress:.1f}%")

        financial_narrative = narrative.financial_summary()
        stock_narrative = narrative.stock_summary()
        insight = f"💡 Atlas Insight: {financial_narrative} {stock_narrative}"
        self.insight_label.configure(text=insight)

        finance_data = self.app.invoice_engine.get_invoice_payment_summary(30)
        if finance_data:
            dates = [row['day'] for row in finance_data]
            issued = [row['total_issued'] or 0 for row in finance_data]
            paid = [row['total_paid'] or 0 for row in finance_data]
            self.ax_finance.clear()
            self.ax_finance.plot(dates, issued, label='Émises', marker='o', color=AtlasConfig.COLORS['primary'])
            self.ax_finance.plot(dates, paid, label='Payées', marker='s', color=AtlasConfig.COLORS['success'])
            self.ax_finance.set_title('Évolution financière (30 jours)')
            self.ax_finance.legend()
            self.ax_finance.tick_params(axis='x', rotation=45)
            self.fig_finance.tight_layout()
            self.canvas_finance.draw()

        stock_movements = self.app.stock_engine.get_movement_summary(30)
        if stock_movements:
            dates = [row['day'] for row in stock_movements]
            ins = [row['total_in'] or 0 for row in stock_movements]
            outs = [row['total_out'] or 0 for row in stock_movements]
            self.ax_stock.clear()
            self.ax_stock.bar(dates, ins, label='Entrées', color=AtlasConfig.COLORS['success'], alpha=0.7)
            self.ax_stock.bar(dates, outs, label='Sorties', color=AtlasConfig.COLORS['danger'], alpha=0.7, bottom=ins)
            self.ax_stock.set_title('Mouvements de stock (30 jours)')
            self.ax_stock.legend()
            self.ax_stock.tick_params(axis='x', rotation=45)
            self.fig_stock.tight_layout()
            self.canvas_stock.draw()

        products = metrics.get_top_products(5)
        prod_text = ""
        for p in products:
            prod_text += f"• {p['name']}: {p['total_qty']} vendus ({p['total_revenue']:.2f}{AtlasConfig.settings['currency']})\n"
        self.products_list.delete("1.0", "end")
        self.products_list.insert("1.0", prod_text or "Aucune vente")

        customers = metrics.get_top_customers(5)
        cust_text = ""
        for c in customers:
            cust_text += f"• {c['name']}: {c['total_spent']:.2f}{AtlasConfig.settings['currency']}\n"
        self.customers_list.delete("1.0", "end")
        self.customers_list.insert("1.0", cust_text or "Aucun client")

        forecast_value = month_ca * 1.05
        self.forecast_label.configure(text=f"{forecast_value:.2f} {AtlasConfig.settings['currency']}")

        overdue = self.app.invoice_engine.get_overdue_invoices()
        low_stock = self.app.stock_engine.get_low_stock_products()
        alerts = ""
        if overdue:
            alerts += f"⚠️ {len(overdue)} facture(s) en retard\n"
        if low_stock:
            alerts += f"⚠️ {len(low_stock)} produit(s) en stock bas\n"
        if not alerts:
            alerts = "Aucune alerte critique"
        self.alerts_list.delete("1.0", "end")
        self.alerts_list.insert("1.0", alerts)

        self.after(60000, self.refresh)

# ========================
# STOCK VIEW (avec scrollbar)
# ========================
