"""
gui/views/analytics_view.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Vue analytique & prévisions.
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

class AtlasAnalyticsView(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, fg_color=AtlasConfig.COLORS["bg"], **kwargs)
        self.app = app
        self.analyzer = None

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

    def create_widgets(self):
        ctk.CTkLabel(self.scrollable_frame, text="Analytics & Prévisions", font=ctk.CTkFont(size=24, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(pady=10)

        frame_controls = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        frame_controls.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(frame_controls, text="Série:").pack(side="left", padx=10)
        self.series_var = tk.StringVar(value="Ventes (CA)")
        series_menu = ctk.CTkOptionMenu(frame_controls, values=["Ventes (CA)", "Ventes (quantités)"], variable=self.series_var)
        series_menu.pack(side="left", padx=10)

        ctk.CTkButton(frame_controls, text="Analyser", command=self.run_analysis, fg_color=AtlasConfig.COLORS["primary"]).pack(side="left", padx=10)

        btn_frame = ctk.CTkFrame(frame_controls, fg_color="transparent")
        btn_frame.pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="ACF/PACF", command=lambda: self.plot_type('acf_pacf'), fg_color=AtlasConfig.COLORS["secondary"]).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="Résidus", command=lambda: self.plot_type('residuals'), fg_color=AtlasConfig.COLORS["secondary"]).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="Décomposition", command=lambda: self.plot_type('decomposition'), fg_color=AtlasConfig.COLORS["secondary"]).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="Prévision", command=lambda: self.plot_type('forecast'), fg_color=AtlasConfig.COLORS["secondary"]).pack(side="left", padx=2)

        self.plot_frame = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        self.plot_frame.pack(fill="both", expand=True, padx=20, pady=10)

        self.figure = plt.Figure(figsize=(8, 5), dpi=100)
        self.canvas_plot = FigureCanvasTkAgg(self.figure, master=self.plot_frame)
        self.canvas_plot.get_tk_widget().pack(fill="both", expand=True)

        comp_frame = ctk.CTkFrame(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        comp_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(comp_frame, text="Comparaison:", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left", padx=10)
        ctk.CTkLabel(comp_frame, text="Période 1 (YYYY-MM):").pack(side="left", padx=5)
        self.period1_entry = ctk.CTkEntry(comp_frame, width=80)
        self.period1_entry.insert(0, (datetime.now() - timedelta(days=30)).strftime("%Y-%m"))
        self.period1_entry.pack(side="left", padx=5)

        ctk.CTkLabel(comp_frame, text="Période 2 (YYYY-MM):").pack(side="left", padx=5)
        self.period2_entry = ctk.CTkEntry(comp_frame, width=80)
        self.period2_entry.insert(0, datetime.now().strftime("%Y-%m"))
        self.period2_entry.pack(side="left", padx=5)

        ctk.CTkButton(comp_frame, text="Comparer", command=self.run_comparison, fg_color=AtlasConfig.COLORS["warning"], text_color="black").pack(side="left", padx=10)

        btn_export = ctk.CTkButton(self.scrollable_frame, text="Exporter rapport PDF", command=self.export_report_pdf, fg_color=AtlasConfig.COLORS["secondary"])
        btn_export.pack(pady=10)

    def run_analysis(self):
        serie_type = self.series_var.get()
        if "CA" in serie_type:
            field = "total_ttc"
        else:
            field = "SUM(il.quantity)"

        rows = self.app.db.fetch_all(f"""
            SELECT date(i.invoice_date) as day, {field} as value
            FROM invoices i
            LEFT JOIN invoice_lines il ON i.id = il.invoice_id
            WHERE i.invoice_date >= date('now', '-90 days') AND i.status != 'draft'
            GROUP BY day
            ORDER BY day
        """)

        if not rows:
            messagebox.showwarning("Pas de données", "Aucune vente trouvée pour l'analyse")
            return

        dates = [row['day'] for row in rows]
        values = [row['value'] for row in rows]
        series = pd.Series(values, index=pd.to_datetime(dates))
        series = series.asfreq('D').fillna(0)

        if len(series) < 10:
            messagebox.showerror("Données insuffisantes", "Pas assez de données pour l'analyse (minimum 10 points).")
            return

        self.analyzer = AtlasTimeSeriesAnalyzer(series)
        stats = self.analyzer.test_stationarity()
        self.analyzer.detect_seasonality()
        order, seasonal_order, aic = self.analyzer.auto_sarima_manual(max_p=3, max_d=1, max_q=3, max_P=1, max_D=1, max_Q=1)
        if order:
            self.analyzer.forecast(steps=30)
            self.plot_type('forecast')
            messagebox.showinfo("Modèle sélectionné", f"Ordre SARIMA: {order} x {seasonal_order}\nAIC: {aic:.2f}")
        else:
            messagebox.showerror("Erreur", "Aucun modèle n'a pu être ajusté")

    def plot_type(self, plot_type):
        if self.analyzer is None:
            messagebox.showwarning("Attention", "Veuillez d'abord lancer une analyse")
            return
        self.analyzer.plot_components(self.figure, plot_type)
        self.canvas_plot.draw()

    def run_comparison(self):
        p1 = self.period1_entry.get()
        p2 = self.period2_entry.get()
        try:
            comp = self.app.invoice_engine.comparative_analytics(p1, p2)
            msg = f"Période {p1} : CA {comp['period1']['revenue']:.2f} {AtlasConfig.settings['currency']}\nPériode {p2} : CA {comp['period2']['revenue']:.2f} {AtlasConfig.settings['currency']}\n"
            if comp['period1']['revenue'] > 0:
                change = (comp['period2']['revenue'] - comp['period1']['revenue']) / comp['period1']['revenue'] * 100
                msg += f"Variation : {change:+.1f}%"
            messagebox.showinfo("Comparaison", msg)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def export_report_pdf(self):
        if self.analyzer is None:
            messagebox.showwarning("Attention", "Veuillez d'abord lancer une analyse")
            return

        path = os.path.join(AtlasConfig.REPORTS_DIR, f"rapport_analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")

        doc = SimpleDocTemplate(path, pagesize=A4,
                                rightMargin=72, leftMargin=72,
                                topMargin=72, bottomMargin=72)
        story = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            alignment=1,
            spaceAfter=20,
            textColor=colors.HexColor("#0F172A")
        )
        section_style = ParagraphStyle(
            'Section',
            parent=styles['Heading2'],
            fontSize=12,
            textColor=colors.HexColor("#3F6FA8"),
            spaceAfter=10
        )
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=6
        )

        header_data = [
            [Paragraph(f"<b>{AtlasConfig.settings['company_name']}</b>", normal_style),
             Paragraph("Rapport d'analyse", normal_style)],
            [Paragraph(AtlasConfig.settings.get('company_address', ''), normal_style),
             Paragraph(f"Date: {datetime.now().strftime(AtlasConfig.settings['date_format'])}", normal_style)],
        ]
        header_table = Table(header_data, colWidths=[250, 250])
        header_table.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 1, colors.black),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 10),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 12))

        story.append(Paragraph("RAPPORT D'ANALYSE STATISTIQUE", title_style))
        story.append(Spacer(1, 12))

        narrative = AtlasNarrativeEngine(self.app.db, self.app)
        financial_summary = narrative.financial_summary()
        stock_summary = narrative.stock_summary()
        story.append(Paragraph("Synthèse financière", section_style))
        story.append(Paragraph(financial_summary, normal_style))
        story.append(Spacer(1, 6))
        story.append(Paragraph("État des stocks", section_style))
        story.append(Paragraph(stock_summary, normal_style))
        story.append(Spacer(1, 12))

        if self.analyzer.adf_result:
            story.append(Paragraph("Tests de stationnarité", section_style))
            story.append(Paragraph(f"Test ADF : statistique = {self.analyzer.adf_result[0]:.4f}, p-value = {self.analyzer.adf_result[1]:.4f}", normal_style))
            story.append(Paragraph(f"Test KPSS : statistique = {self.analyzer.kpss_result[0]:.4f}, p-value = {self.analyzer.kpss_result[1]:.4f}", normal_style))
            story.append(Spacer(1, 6))

        if self.analyzer.model_fit:
            story.append(Paragraph("Modèle SARIMA", section_style))
            story.append(Paragraph(f"Ordre : {self.analyzer.best_order} x {self.analyzer.best_seasonal_order}", normal_style))
            story.append(Paragraph(f"AIC : {self.analyzer.model_fit.aic:.2f}, BIC : {self.analyzer.model_fit.bic:.2f}", normal_style))
            story.append(Spacer(1, 6))

        if self.analyzer.forecast_result:
            story.append(Paragraph("Prévisions sur 30 jours", section_style))
            forecast = self.analyzer.forecast_result['forecast']
            conf_int = self.analyzer.forecast_result['conf_int']

            data = [["Jour", "Prévision", "Intervalle bas", "Intervalle haut"]]
            for i, val in enumerate(forecast.values):
                data.append([f"J{i+1}", f"{val:.2f} {AtlasConfig.settings['currency']}",
                             f"{conf_int[i,0]:.2f} {AtlasConfig.settings['currency']}",
                             f"{conf_int[i,1]:.2f} {AtlasConfig.settings['currency']}"])
            table = Table(data, colWidths=[50, 100, 100, 100])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#3F6FA8")),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('PADDING', (0,0), (-1,-1), 6),
            ]))
            story.append(table)
            story.append(Spacer(1, 12))

            forecast_narrative = narrative.forecast_narrative(forecast.values, conf_int)
            story.append(Paragraph("Analyse des prévisions", section_style))
            story.append(Paragraph(forecast_narrative, normal_style))

        temp_img = os.path.join(tempfile.gettempdir(), "atlas_temp_plot.png")
        self.figure.savefig(temp_img, dpi=150)

        if os.path.exists(temp_img):
            img = RLImage(temp_img, width=6*inch, height=4*inch)
            story.append(Spacer(1, 12))
            story.append(Paragraph("Graphique de la série", section_style))
            story.append(img)
        else:
            story.append(Paragraph("(Graphique non disponible)", normal_style))

        story.append(Spacer(1, 30))
        footer_text = "Rapport généré automatiquement par Dataikos Atlas – Données confidentielles."
        story.append(Paragraph(footer_text, ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey, alignment=1)))

        doc.build(story)
        self.app.log_action("analytics_export_pdf", f"Rapport PDF généré")
        messagebox.showinfo("Succès", f"Rapport PDF généré : {path}")

# ========================
# ACTIVITY LOG VIEW (avec scrollbar)
# ========================
