"""
gui/views/finance_view.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Vue facturation & finances.
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

class AtlasFinanceView(ctk.CTkFrame):
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
        self.load_invoices()

    def create_widgets(self):
        toolbar = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(toolbar, text="Finance & Factures", font=ctk.CTkFont(size=20, weight="bold"), text_color=AtlasConfig.COLORS["sidebar"]).pack(side="left")

        if self.app.current_user['role'] in ['admin', 'manager', 'commercial']:
            btn_new = ctk.CTkButton(toolbar, text="+ Nouvelle facture", command=self.new_invoice_dialog, fg_color=AtlasConfig.COLORS["primary"], hover_color="#e06712")
            btn_new.pack(side="right", padx=5)

        self.tabview = ctk.CTkTabview(self.scrollable_frame, fg_color=AtlasConfig.COLORS["card"], segmented_button_selected_color=AtlasConfig.COLORS["primary"])
        self.tabview.pack(fill="both", expand=True, padx=20, pady=10)

        self.invoice_tab = self.tabview.add("Factures")
        self.create_invoice_tab()

        self.client_tab = self.tabview.add("Notation clients")
        self.create_client_tab()

        self.cashflow_tab = self.tabview.add("Trésorerie prévisionnelle")
        self.create_cashflow_tab()

    def create_invoice_tab(self):
        filter_frame = ctk.CTkFrame(self.invoice_tab, fg_color="transparent")
        filter_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(filter_frame, text="Statut:").pack(side="left", padx=10)
        self.status_var = tk.StringVar(value="Tous")
        statuses = ["Tous", "draft", "sent", "paid", "partial", "overdue"]
        status_menu = ctk.CTkOptionMenu(filter_frame, values=statuses, variable=self.status_var, command=lambda x: self.load_invoices())
        status_menu.pack(side="left", padx=10)

        self.tree_frame = ctk.CTkFrame(self.invoice_tab, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        self.tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("N°", "Client", "Date", "Échéance", "Total TTC", "Statut")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c))
            self.tree.column(col, width=120)

        scrollbar_tree = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_tree.set)
        scrollbar_tree.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<Double-1>", self.view_invoice)

    def sort_treeview(self, col):
        data = [(self.tree.set(child, col), child) for child in self.tree.get_children('')]
        data.sort()
        for index, (val, child) in enumerate(data):
            self.tree.move(child, '', index)

    def load_invoices(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        status = self.status_var.get()
        if status == "Tous":
            invoices = self.app.db.fetch_all("""
                SELECT i.*, c.name as customer_name FROM invoices i
                JOIN customers c ON i.customer_id = c.id
                ORDER BY i.invoice_date DESC LIMIT 100
            """)
        elif status == "overdue":
            today = datetime.now().strftime("%Y-%m-%d")
            invoices = self.app.db.fetch_all("""
                SELECT i.*, c.name as customer_name FROM invoices i
                JOIN customers c ON i.customer_id = c.id
                WHERE i.due_date < ? AND i.status IN ('sent', 'partial')
                ORDER BY i.invoice_date DESC LIMIT 100
            """, (today,))
        else:
            invoices = self.app.db.fetch_all("""
                SELECT i.*, c.name as customer_name FROM invoices i
                JOIN customers c ON i.customer_id = c.id
                WHERE i.status = ?
                ORDER BY i.invoice_date DESC LIMIT 100
            """, (status,))

        for inv in invoices:
            self.tree.insert("", "end", iid=inv['id'], values=(
                inv['invoice_number'],
                inv['customer_name'],
                inv['invoice_date'],
                inv['due_date'],
                f"{inv['total_ttc']:.2f} {AtlasConfig.settings['currency']}",
                inv['status']
            ))

    def create_client_tab(self):
        self.client_tree_frame = ctk.CTkFrame(self.client_tab, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        self.client_tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("ID", "Nom", "Email", "Score", "Crédit utilisé")
        self.client_tree = ttk.Treeview(self.client_tree_frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.client_tree.heading(col, text=col)
            self.client_tree.column(col, width=100)

        scrollbar_tree = ttk.Scrollbar(self.client_tree_frame, orient="vertical", command=self.client_tree.yview)
        self.client_tree.configure(yscrollcommand=scrollbar_tree.set)
        scrollbar_tree.pack(side="right", fill="y")
        self.client_tree.pack(side="left", fill="both", expand=True)

        self.load_client_scores()

    def load_client_scores(self):
        for row in self.client_tree.get_children():
            self.client_tree.delete(row)

        clients = self.app.db.fetch_all("SELECT id, name, email, credit_limit FROM customers WHERE active=1")
        for c in clients:
            score = self.app.invoice_engine.client_score(c['id'])
            used = self.app.db.fetch_one("""
                SELECT SUM(total_ttc - IFNULL((SELECT SUM(amount) FROM payments WHERE invoice_id=invoices.id),0)) as due
                FROM invoices WHERE customer_id=? AND status IN ('sent','partial')
            """, (c['id'],))['due'] or 0
            self.client_tree.insert("", "end", iid=c['id'], values=(
                c['id'], c['name'], c['email'], f"{score:.0f}", f"{used:.2f} {AtlasConfig.settings['currency']}"
            ))

    def create_cashflow_tab(self):
        frame = ctk.CTkFrame(self.cashflow_tab, fg_color=AtlasConfig.COLORS["card"], corner_radius=14)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(frame, text="Projection de trésorerie (3 mois)", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        self.cashflow_text = ctk.CTkTextbox(frame, height=200, wrap="none")
        self.cashflow_text.pack(fill="both", expand=True, padx=10, pady=10)

        self.refresh_cashflow()

    def refresh_cashflow(self):
        df = self.app.invoice_engine.cash_flow_projection()
        text = ""
        for _, row in df.iterrows():
            text += f"{row['month']}: {row['inflow']:.2f} {AtlasConfig.settings['currency']}\n"
        self.cashflow_text.delete("1.0", "end")
        self.cashflow_text.insert("1.0", text)

    def new_invoice_dialog(self):
        if self.app.current_user['role'] not in ['admin', 'manager', 'commercial']:
            messagebox.showerror("Permission", "Vous n'avez pas les droits pour créer une facture.")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Nouvelle facture")
        dialog.geometry("700x600")
        dialog.transient(self)
        dialog.grab_set()

        client_frame = ctk.CTkFrame(dialog)
        client_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(client_frame, text="Client:").pack(side="left", padx=5)
        clients = self.app.db.fetch_all("SELECT id, name FROM customers WHERE active=1")
        client_names = [f"{c['id']} - {c['name']}" for c in clients]
        client_var = tk.StringVar()
        client_menu = ctk.CTkOptionMenu(client_frame, values=client_names, variable=client_var)
        client_menu.pack(side="left", padx=5, fill="x", expand=True)

        date_frame = ctk.CTkFrame(dialog)
        date_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(date_frame, text="Date facture:").pack(side="left", padx=5)
        if HAS_TKCALENDAR and DateEntry:
            date_entry = DateEntry(date_frame, width=12, background='darkblue', foreground='white', borderwidth=2)
            date_entry.pack(side="left", padx=5)
        else:
            date_entry = ctk.CTkEntry(date_frame, width=120)
            date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
            date_entry.pack(side="left", padx=5)

        ctk.CTkLabel(date_frame, text="Échéance:").pack(side="left", padx=5)
        if HAS_TKCALENDAR and DateEntry:
            due_entry = DateEntry(date_frame, width=12, background='darkblue', foreground='white', borderwidth=2)
            due_entry.pack(side="left", padx=5)
        else:
            due_entry = ctk.CTkEntry(date_frame, width=120)
            due_entry.insert(0, (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"))
            due_entry.pack(side="left", padx=5)

        lines_frame = ctk.CTkScrollableFrame(dialog, label_text="Lignes")
        lines_frame.pack(fill="both", expand=True, padx=10, pady=5)

        lines = []

        def add_line():
            line_frame = ctk.CTkFrame(lines_frame)
            line_frame.pack(fill="x", pady=2)

            ctk.CTkLabel(line_frame, text="Produit:").grid(row=0, column=0, padx=2)
            products = self.app.db.fetch_all("SELECT id, name, unit_price FROM products WHERE active=1")
            prod_names = [f"{p['id']} - {p['name']}" for p in products]
            prod_var = tk.StringVar()
            prod_menu = ctk.CTkOptionMenu(line_frame, values=[""] + prod_names, variable=prod_var, width=150)
            prod_menu.grid(row=0, column=1, padx=2)

            ctk.CTkLabel(line_frame, text="Description:").grid(row=0, column=2, padx=2)
            desc_entry = ctk.CTkEntry(line_frame, width=150)
            desc_entry.grid(row=0, column=3, padx=2)

            ctk.CTkLabel(line_frame, text="Qté:").grid(row=0, column=4, padx=2)
            qty_entry = ctk.CTkEntry(line_frame, width=50)
            qty_entry.insert(0, "1")
            qty_entry.grid(row=0, column=5, padx=2)

            ctk.CTkLabel(line_frame, text="Prix U.:").grid(row=0, column=6, padx=2)
            price_entry = ctk.CTkEntry(line_frame, width=70)
            price_entry.grid(row=0, column=7, padx=2)

            ctk.CTkLabel(line_frame, text="TVA %:").grid(row=0, column=8, padx=2)
            tax_entry = ctk.CTkEntry(line_frame, width=40)
            tax_entry.insert(0, str(AtlasConfig.settings['vat_rate']))
            tax_entry.grid(row=0, column=9, padx=2)

            ctk.CTkLabel(line_frame, text="Remise %:").grid(row=0, column=10, padx=2)
            disc_entry = ctk.CTkEntry(line_frame, width=40)
            disc_entry.insert(0, "0")
            disc_entry.grid(row=0, column=11, padx=2)

            def remove():
                line_frame.destroy()
                lines.remove(line_data)
                update_totals()

            btn_del = ctk.CTkButton(line_frame, text="X", width=30, command=remove, fg_color=AtlasConfig.COLORS["danger"])
            btn_del.grid(row=0, column=12, padx=2)

            line_data = {
                'frame': line_frame,
                'prod_var': prod_var,
                'desc_entry': desc_entry,
                'qty_entry': qty_entry,
                'price_entry': price_entry,
                'tax_entry': tax_entry,
                'disc_entry': disc_entry
            }
            lines.append(line_data)

            for entry in [qty_entry, price_entry, tax_entry, disc_entry]:
                entry.bind("<KeyRelease>", lambda e: update_totals())

        btn_add_line = ctk.CTkButton(dialog, text="Ajouter une ligne", command=add_line, fg_color=AtlasConfig.COLORS["secondary"])
        btn_add_line.pack(pady=5)

        total_frame = ctk.CTkFrame(dialog)
        total_frame.pack(fill="x", padx=10, pady=5)
        total_ht_label = ctk.CTkLabel(total_frame, text=f"Total HT: 0.00 {AtlasConfig.settings['currency']}")
        total_ht_label.pack(side="left", padx=10)
        total_tax_label = ctk.CTkLabel(total_frame, text=f"TVA: 0.00 {AtlasConfig.settings['currency']}")
        total_tax_label.pack(side="left", padx=10)
        total_ttc_label = ctk.CTkLabel(total_frame, text=f"Total TTC: 0.00 {AtlasConfig.settings['currency']}", font=ctk.CTkFont(weight="bold"))
        total_ttc_label.pack(side="left", padx=10)

        def update_totals():
            total_ht = 0.0
            total_tax = 0.0
            for line in lines:
                try:
                    qty = float(line['qty_entry'].get() or 0)
                    price = float(line['price_entry'].get() or 0)
                    tax = float(line['tax_entry'].get() or 0)
                    disc = float(line['disc_entry'].get() or 0)
                    if disc > 100:
                        disc = 100
                    line_ht = qty * price * (1 - disc/100)
                    line_tax = line_ht * tax / 100
                    total_ht += line_ht
                    total_tax += line_tax
                except:
                    pass
            total_ttc = total_ht + total_tax
            total_ht_label.configure(text=f"Total HT: {total_ht:.2f} {AtlasConfig.settings['currency']}")
            total_tax_label.configure(text=f"TVA: {total_tax:.2f} {AtlasConfig.settings['currency']}")
            total_ttc_label.configure(text=f"Total TTC: {total_ttc:.2f} {AtlasConfig.settings['currency']}")

        def save_invoice():
            try:
                client_str = client_var.get()
                if not client_str:
                    messagebox.showerror("Erreur", "Sélectionnez un client")
                    return
                customer_id = int(client_str.split(" - ")[0])

                invoice_lines = []
                for line in lines:
                    qty = float(line['qty_entry'].get() or 0)
                    if qty <= 0:
                        continue
                    price = float(line['price_entry'].get() or 0)
                    tax = float(line['tax_entry'].get() or 0)
                    disc = float(line['disc_entry'].get() or 0)

                    desc = line['desc_entry'].get().strip()
                    if not desc:
                        prod_str = line['prod_var'].get()
                        if prod_str:
                            desc = prod_str.split(" - ", 1)[1] if " - " in prod_str else prod_str
                        else:
                            desc = "Article"

                    product_id = None
                    if line['prod_var'].get():
                        try:
                            product_id = int(line['prod_var'].get().split(" - ")[0])
                        except:
                            pass

                    invoice_lines.append({
                        'product_id': product_id,
                        'description': desc,
                        'quantity': qty,
                        'unit_price': price,
                        'tax_rate': tax,
                        'discount': disc
                    })

                if not invoice_lines:
                    messagebox.showerror("Erreur", "Ajoutez au moins une ligne valide")
                    return

                if HAS_TKCALENDAR and DateEntry:
                    invoice_date = date_entry.get_date().strftime("%Y-%m-%d")
                    due_date = due_entry.get_date().strftime("%Y-%m-%d")
                else:
                    invoice_date = date_entry.get()
                    due_date = due_entry.get()

                invoice_id = self.app.invoice_engine.create_invoice(
                    customer_id=customer_id,
                    lines=invoice_lines,
                    invoice_date=invoice_date,
                    due_date=due_date,
                    notes=""
                )
                dialog.destroy()
                self.load_invoices()
                messagebox.showinfo("Succès", f"Facture créée avec le numéro {self.app.db.fetch_one('SELECT invoice_number FROM invoices WHERE id=?', (invoice_id,))['invoice_number']}")
            except Exception as e:
                messagebox.showerror("Erreur", str(e))

        btn_save = ctk.CTkButton(dialog, text="Créer la facture", command=save_invoice, fg_color=AtlasConfig.COLORS["primary"])
        btn_save.pack(pady=10)

        add_line()

    def view_invoice(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        invoice_id = selected[0]
        dialog = ctk.CTkToplevel(self)
        dialog.title("Détails de la facture")
        dialog.geometry("600x500")
        dialog.transient(self)
        dialog.grab_set()

        inv = self.app.db.fetch_one("""
            SELECT i.*, c.name as customer_name, c.address, c.city, c.postal_code, c.country
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            WHERE i.id = ?
        """, (invoice_id,))
        if not inv:
            return

        lines = self.app.db.fetch_all("SELECT * FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))

        text = f"Facture {inv['invoice_number']}\n"
        text += f"Client: {inv['customer_name']}\n"
        text += f"Date: {inv['invoice_date']} - Échéance: {inv['due_date']}\n"
        text += f"Statut: {inv['status']}\n"
        text += "-"*50 + "\n"
        for line in lines:
            text += f"{line['description']} x{line['quantity']} à {line['unit_price']}{AtlasConfig.settings['currency']}"
            if line['discount'] > 0:
                text += f" (remise {line['discount']}%)"
            text += f" = {line['total_ht']}{AtlasConfig.settings['currency']}\n"
        text += "-"*50 + "\n"
        text += f"Total HT: {inv['total_ht']}{AtlasConfig.settings['currency']}\n"
        text += f"TVA: {inv['total_tax']}{AtlasConfig.settings['currency']}\n"
        text += f"Total TTC: {inv['total_ttc']}{AtlasConfig.settings['currency']}\n"

        text_widget = ctk.CTkTextbox(dialog, wrap="word")
        text_widget.pack(fill="both", expand=True, padx=10, pady=10)
        text_widget.insert("1.0", text)
        text_widget.configure(state="disabled")

        btn_export = ctk.CTkButton(dialog, text="Exporter TXT", command=lambda: self.export_txt(int(invoice_id)), fg_color=AtlasConfig.COLORS["secondary"])
        btn_export.pack(pady=5)

        btn_export_pdf = ctk.CTkButton(dialog, text="Exporter PDF", command=lambda: self.export_pdf(int(invoice_id)), fg_color=AtlasConfig.COLORS["primary"])
        btn_export_pdf.pack(pady=5)

        if inv['status'] in ['sent', 'partial']:
            btn_payment = ctk.CTkButton(dialog, text="Enregistrer un paiement", command=lambda: self.payment_dialog(int(invoice_id)), fg_color=AtlasConfig.COLORS["primary"])
            btn_payment.pack(pady=5)

    def export_txt(self, invoice_id):
        try:
            path = self.app.invoice_engine.export_invoice_txt(invoice_id)
            messagebox.showinfo("Succès", f"Fichier TXT généré : {path}")
            if messagebox.askyesno("Ouvrir", "Voulez-vous ouvrir le fichier ?"):
                os.startfile(path)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def export_pdf(self, invoice_id):
        try:
            path = self.app.invoice_engine.export_invoice_pdf(invoice_id)
            messagebox.showinfo("Succès", f"PDF généré : {path}")
            if messagebox.askyesno("Ouvrir", "Voulez-vous ouvrir le PDF ?"):
                os.startfile(path)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def payment_dialog(self, invoice_id):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Enregistrer un paiement")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.grab_set()

        inv = self.app.db.fetch_one("SELECT total_ttc FROM invoices WHERE id = ?", (invoice_id,))
        if not inv:
            return

        paid_total = self.app.db.fetch_one("SELECT SUM(amount) as total FROM payments WHERE invoice_id = ?", (invoice_id,))
        paid = paid_total['total'] or 0.0
        restant = inv['total_ttc'] - paid

        ctk.CTkLabel(dialog, text=f"Montant restant à payer : {restant:.2f} {AtlasConfig.settings['currency']}").pack(pady=10)

        ctk.CTkLabel(dialog, text="Montant:").pack(pady=5)
        amount_entry = ctk.CTkEntry(dialog)
        amount_entry.pack(pady=5)

        ctk.CTkLabel(dialog, text="Méthode:").pack(pady=5)
        method_var = tk.StringVar(value="Espèces")
        method_menu = ctk.CTkOptionMenu(dialog, values=["Espèces", "Carte", "Virement", "Chèque"], variable=method_var)
        method_menu.pack(pady=5)

        ctk.CTkLabel(dialog, text="Référence:").pack(pady=5)
        ref_entry = ctk.CTkEntry(dialog)
        ref_entry.pack(pady=5)

        def save():
            try:
                amount = float(amount_entry.get())
                if amount <= 0:
                    raise ValueError("Montant invalide")
                if amount > restant + 0.01:
                    raise ValueError("Montant trop élevé")
                self.app.payment_engine.record_payment(invoice_id, amount, method_var.get(), ref_entry.get())
                dialog.destroy()
                self.load_invoices()
                messagebox.showinfo("Succès", "Paiement enregistré")
            except Exception as e:
                messagebox.showerror("Erreur", str(e))

        ctk.CTkButton(dialog, text="Enregistrer", command=save, fg_color=AtlasConfig.COLORS["primary"]).pack(pady=20)

# ========================
# ANALYTICS VIEW (avec scrollbar)
# ========================
