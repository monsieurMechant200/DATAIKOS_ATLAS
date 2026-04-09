"""
core/invoice_payment.py
~~~~~~~~~~~~~~~~~~~~~~~
Moteurs de facturation et de paiement.
"""
from __future__ import annotations
import os
import csv
import json
import hashlib
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import threading
import webbrowser

import pandas as pd
import numpy as np

from config   import AtlasConfig
from database import AtlasDatabase

class InvoiceEngine:
    def __init__(self, db: AtlasDatabase, app):
        self.db = db
        self.app = app

    def generate_invoice_number(self) -> str:
        if not AtlasConfig.settings["invoice_auto_numbering"]:
            return ""
        last = self.db.fetch_one("SELECT invoice_number FROM invoices ORDER BY id DESC LIMIT 1")
        if last:
            parts = last['invoice_number'].split('-')
            if len(parts) == 3 and parts[0] == "FAC":
                year = datetime.now().strftime("%Y")
                if parts[1] == year:
                    num = int(parts[2]) + 1
                    return f"FAC-{year}-{num:04d}"
        return f"FAC-{datetime.now().strftime('%Y')}-0001"

    def create_invoice(self, customer_id: int, lines: List[Dict], invoice_date: str = None,
                       due_date: str = None, notes: str = "") -> int:
        customer = self.db.fetch_one("SELECT id FROM customers WHERE id = ? AND active = 1", (customer_id,))
        if not customer:
            raise ValueError("Client invalide ou inactif")

        if not lines:
            raise ValueError("La facture doit contenir au moins une ligne")

        if not invoice_date:
            invoice_date = datetime.now().strftime("%Y-%m-%d")
        if not due_date:
            due_days = AtlasConfig.settings.get("payment_terms", 30)
            due_date = (datetime.now() + timedelta(days=due_days)).strftime("%Y-%m-%d")

        total_ht = 0.0
        total_tax = 0.0
        for line in lines:
            if line['quantity'] <= 0:
                raise ValueError("La quantité doit être positive")
            if line['unit_price'] < 0:
                raise ValueError("Le prix unitaire ne peut être négatif")
            if line.get('discount', 0) < 0 or line.get('discount', 0) > 100:
                raise ValueError("La remise doit être entre 0 et 100")

            line_ht = line['quantity'] * line['unit_price'] * (1 - line.get('discount', 0)/100)
            line_tax = line_ht * line.get('tax_rate', 0) / 100
            total_ht += line_ht
            total_tax += line_tax
            line['total_ht'] = line_ht

        total_ttc = total_ht + total_tax

        invoice_number = self.generate_invoice_number()

        self.db.execute("""
            INSERT INTO invoices (invoice_number, customer_id, invoice_date, due_date,
                                  total_ht, total_tax, total_ttc, notes, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'sent', ?)
        """, (invoice_number, customer_id, invoice_date, due_date, total_ht, total_tax, total_ttc, notes, self.app.current_user['id']))
        invoice_id = self.db.cursor.lastrowid

        for line in lines:
            self.db.execute("""
                INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price,
                                           tax_rate, discount, total_ht)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (invoice_id, line.get('product_id'), line['description'], line['quantity'],
                  line['unit_price'], line.get('tax_rate', 0), line.get('discount', 0), line['total_ht']))

            if line.get('product_id'):
                product = self.db.fetch_one("SELECT current_stock FROM products WHERE id = ?", (line['product_id'],))
                if product and product['current_stock'] < line['quantity']:
                    raise ValueError(f"Stock insuffisant pour le produit {line['description']}")

                self.db.execute("""
                    INSERT INTO stock_movements (product_id, movement_type, quantity, unit_price, reason, reference, user_id)
                    VALUES (?, 'out', ?, ?, 'Vente', ?, ?)
                """, (line['product_id'], line['quantity'], line['unit_price'], invoice_number, self.app.current_user['id']))
                self.db.execute("UPDATE products SET current_stock = current_stock - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (line['quantity'], line['product_id']))

        self.db.commit()
        self.app.log_action("invoice_created", f"Facture {invoice_number} créée")
        return invoice_id

    def get_invoices(self, status: Optional[str] = None, limit: int = 100):
        query = "SELECT i.*, c.name as customer_name, u.full_name as creator_name FROM invoices i JOIN customers c ON i.customer_id = c.id LEFT JOIN users u ON i.created_by = u.id"
        params = []
        if status:
            query += " WHERE i.status = ?"
            params.append(status)
        query += " ORDER BY i.invoice_date DESC LIMIT ?"
        params.append(limit)
        return self.db.fetch_all(query, tuple(params))

    def get_invoice_payment_summary(self, days: int = 30):
        rows = self.db.fetch_all("""
            SELECT date(invoice_date) as day,
                   SUM(total_ttc) as total_issued,
                   SUM(CASE WHEN status='paid' THEN total_ttc ELSE 0 END) as total_paid
            FROM invoices
            WHERE invoice_date >= date('now', ?) AND status != 'draft'
            GROUP BY day
            ORDER BY day
        """, (f'-{days} days',))
        return rows

    def mark_as_paid(self, invoice_id: int, amount: float, method: str, payment_date: str = None):
        if not payment_date:
            payment_date = datetime.now().strftime("%Y-%m-%d")

        paid_total = self.db.fetch_one("SELECT SUM(amount) as total FROM payments WHERE invoice_id = ?", (invoice_id,))
        paid = paid_total['total'] or 0.0
        invoice = self.db.fetch_one("SELECT total_ttc FROM invoices WHERE id = ?", (invoice_id,))
        if not invoice:
            raise ValueError("Facture introuvable")

        new_paid = paid + amount
        if new_paid > invoice['total_ttc'] + 0.01:
            raise ValueError("Le montant total payé dépasse le montant de la facture")

        self.db.execute("""
            INSERT INTO payments (invoice_id, payment_date, amount, method)
            VALUES (?, ?, ?, ?)
        """, (invoice_id, payment_date, amount, method))

        if abs(new_paid - invoice['total_ttc']) < 0.01:
            status = 'paid'
        else:
            status = 'partial'

        self.db.execute("UPDATE invoices SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (status, invoice_id))
        self.db.commit()
        self.app.log_action("payment_recorded", f"Facture {invoice_id} - {amount} {method}")

    def get_overdue_invoices(self):
        today = datetime.now().strftime("%Y-%m-%d")
        return self.db.fetch_all("""
            SELECT i.*, c.name as customer_name FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            WHERE i.due_date < ? AND i.status IN ('sent', 'partial')
        """, (today,))

    def export_invoice_txt(self, invoice_id: int, output_path: str = None):
        invoice = self.db.fetch_one("""
            SELECT i.*, c.name as customer_name, c.address, c.city, c.postal_code, c.country, c.email, u.full_name as creator_name
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            LEFT JOIN users u ON i.created_by = u.id
            WHERE i.id = ?
        """, (invoice_id,))
        if not invoice:
            raise ValueError("Facture introuvable")

        lines = self.db.fetch_all("SELECT * FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))

        if not output_path:
            os.makedirs(AtlasConfig.REPORTS_DIR, exist_ok=True)
            output_path = os.path.join(AtlasConfig.REPORTS_DIR, f"facture_{invoice['invoice_number']}.txt")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("="*60 + "\n")
            f.write(f"FACTURE {invoice['invoice_number']}\n".center(60) + "\n")
            f.write("="*60 + "\n\n")

            f.write(f"Émetteur : {AtlasConfig.settings['company_name']}\n\n")

            f.write("Client :\n")
            f.write(f"  {invoice['customer_name']}\n")
            if invoice['address']:
                f.write(f"  {invoice['address']}\n")
            if invoice['city']:
                f.write(f"  {invoice['postal_code']} {invoice['city']}\n")
            if invoice['country']:
                f.write(f"  {invoice['country']}\n")
            f.write(f"  Email : {invoice['email'] or ''}\n\n")

            f.write(f"Date de facture : {invoice['invoice_date']}\n")
            f.write(f"Date d'échéance : {invoice['due_date']}\n\n")

            f.write(f"Créée par : {invoice['creator_name'] or 'Inconnu'}\n\n")

            f.write("-"*60 + "\n")
            f.write(f"{'Description':<30} {'Qté':>5} {'Prix U.':>10} {'TVA':>6} {'Total HT':>10}\n")
            f.write("-"*60 + "\n")

            for line in lines:
                desc = line['description'][:28] + ".." if len(line['description']) > 28 else line['description']
                f.write(f"{desc:<30} {line['quantity']:>5} {line['unit_price']:>10.2f} {line['tax_rate']:>5.1f}% {line['total_ht']:>10.2f}\n")

            f.write("-"*60 + "\n")
            f.write(f"{'Total HT':>52} {invoice['total_ht']:.2f} {AtlasConfig.settings['currency']}\n")
            f.write(f"{'TVA':>52} {invoice['total_tax']:.2f} {AtlasConfig.settings['currency']}\n")
            f.write(f"{'Total TTC':>52} {invoice['total_ttc']:.2f} {AtlasConfig.settings['currency']}\n")
            f.write("="*60 + "\n")

            if invoice['notes']:
                f.write(f"\nNotes : {invoice['notes']}\n")

        return output_path

    def export_invoice_pdf(self, invoice_id: int, output_path: str = None):
        invoice = self.db.fetch_one("""
            SELECT i.*, c.name as customer_name, c.address, c.city, c.postal_code, c.country, c.email,
                   u.full_name as creator_name
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            LEFT JOIN users u ON i.created_by = u.id
            WHERE i.id = ?
        """, (invoice_id,))
        if not invoice:
            raise ValueError("Facture introuvable")

        lines = self.db.fetch_all("SELECT * FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))

        if not output_path:
            os.makedirs(AtlasConfig.REPORTS_DIR, exist_ok=True)
            output_path = os.path.join(AtlasConfig.REPORTS_DIR, f"facture_{invoice['invoice_number']}.pdf")

        doc = SimpleDocTemplate(output_path, pagesize=A4,
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
        signature_style = ParagraphStyle(
            'Signature',
            parent=styles['Normal'],
            fontSize=10,
            alignment=2,
            spaceAfter=6
        )

        company_info = []
        if AtlasConfig.settings.get('logo_path') and os.path.exists(AtlasConfig.settings['logo_path']):
            try:
                logo = RLImage(AtlasConfig.settings['logo_path'], width=1.5*inch, height=0.75*inch)
                company_info.append(logo)
            except:
                company_info.append(Paragraph("", normal_style))
        else:
            company_info.append(Paragraph("", normal_style))

        company_text = f"""
        <b>{AtlasConfig.settings['company_name']}</b><br/>
        {AtlasConfig.settings.get('company_address', '')}<br/>
        Tél: {AtlasConfig.settings.get('company_phone', '')}<br/>
        Email: {AtlasConfig.settings.get('company_email', '')}<br/>
        N° fiscal: {AtlasConfig.settings.get('company_tax_id', '')}
        """
        company_info.append(Paragraph(company_text, normal_style))

        header_table = Table([company_info], colWidths=[150, 350])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ALIGN', (0,0), (0,0), 'LEFT'),
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 12))

        story.append(Paragraph(f"FACTURE N° {invoice['invoice_number']}", title_style))
        story.append(Spacer(1, 12))

        client_date_data = [
            [Paragraph("<b>Client</b>", section_style),
             Paragraph("<b>Détails</b>", section_style)],
            [f"{invoice['customer_name']}",
             f"Date: {invoice['invoice_date']}"],
            [f"{invoice['address'] or ''}",
             f"Échéance: {invoice['due_date']}"],
            [f"{invoice['postal_code'] or ''} {invoice['city'] or ''}",
             f"Créée par: {invoice['creator_name'] or 'Inconnu'}"],
            [f"{invoice['country'] or ''}", ""],
            [f"Email: {invoice['email'] or ''}", ""]
        ]
        client_table = Table(client_date_data, colWidths=[250, 250])
        client_table.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 1, colors.black),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#3F6FA8")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 8),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ]))
        story.append(client_table)
        story.append(Spacer(1, 12))

        story.append(Paragraph("DÉTAILS", section_style))

        data = [["Description", "Qté", "Prix unitaire", "TVA %", "Total HT"]]
        for line in lines:
            data.append([
                line['description'],
                str(line['quantity']),
                f"{line['unit_price']:.2f} {AtlasConfig.settings['currency']}",
                f"{line['tax_rate']}%",
                f"{line['total_ht']:.2f} {AtlasConfig.settings['currency']}"
            ])

        if len(data) < 12:
            for _ in range(12 - len(data)):
                data.append(["", "", "", "", ""])

        table = Table(data, colWidths=[200, 50, 80, 50, 80])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#3F6FA8")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 10),
            ('BOTTOMPADDING', (0,0), (-1,0), 8),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor("#F9FAFB")),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

        total_data = [
            ["", "", "Total HT:", f"{invoice['total_ht']:.2f} {AtlasConfig.settings['currency']}"],
            ["", "", "TVA:", f"{invoice['total_tax']:.2f} {AtlasConfig.settings['currency']}"],
            ["", "", "Total TTC:", f"{invoice['total_ttc']:.2f} {AtlasConfig.settings['currency']}"]
        ]
        total_table = Table(total_data, colWidths=[200, 200, 100, 100])
        total_table.setStyle(TableStyle([
            ('ALIGN', (2,0), (2,-1), 'RIGHT'),
            ('ALIGN', (3,0), (3,-1), 'RIGHT'),
            ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
            ('FONTNAME', (3,0), (3,-1), 'Helvetica-Bold'),
            ('LINEABOVE', (2,-1), (3,-1), 1, colors.black),
            ('PADDING', (2,0), (3,-1), 6),
        ]))
        story.append(total_table)
        story.append(Spacer(1, 12))

        signature_data = [
            ["", ""],
            ["Signature du client", "Cachet et signature du vendeur"],
            ["", ""],
            ["", f"({invoice['creator_name'] or 'Agent'})"]
        ]
        signature_table = Table(signature_data, colWidths=[250, 250])
        signature_table.setStyle(TableStyle([
            ('LINEABOVE', (0,1), (0,1), 1, colors.black),
            ('LINEABOVE', (1,1), (1,1), 1, colors.black),
            ('ALIGN', (0,1), (0,1), 'CENTER'),
            ('ALIGN', (1,1), (1,1), 'CENTER'),
            ('VALIGN', (0,1), (1,1), 'BOTTOM'),
        ]))
        story.append(signature_table)
        story.append(Spacer(1, 6))

        if invoice['notes']:
            story.append(Paragraph(f"Commentaires: {invoice['notes']}", normal_style))

        story.append(Spacer(1, 30))
        footer_text = "Document généré automatiquement par Dataikos Atlas – Merci de votre confiance."
        story.append(Paragraph(footer_text, ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey, alignment=1)))

        doc.build(story)
        self.app.log_action("invoice_export_pdf", f"Facture {invoice['invoice_number']} exportée")
        return output_path

    def client_score(self, customer_id: int) -> float:
        invoices = self.db.fetch_all("SELECT * FROM invoices WHERE customer_id=? AND status!='draft'", (customer_id,))
        if not invoices:
            return 50
        total_paid_on_time = 0
        total_invoices = 0
        for inv in invoices:
            if inv['status'] == 'paid':
                total_paid_on_time += 1
            total_invoices += 1
        reliability = (total_paid_on_time / total_invoices) * 100 if total_invoices else 50
        total_spent = sum(i['total_ttc'] for i in invoices)
        volume_score = min(30, total_spent / 1000)
        first_inv = self.db.fetch_one("SELECT MIN(invoice_date) as first FROM invoices WHERE customer_id=?", (customer_id,))
        if first_inv and first_inv['first']:
            days_active = (datetime.now() - datetime.strptime(first_inv['first'], "%Y-%m-%d")).days
            tenure_score = min(20, days_active / 30)
        else:
            tenure_score = 0
        return min(100, reliability * 0.5 + volume_score + tenure_score)

    def unpaid_severity(self, invoice_id: int) -> str:
        inv = self.db.fetch_one("SELECT due_date, total_ttc FROM invoices WHERE id=?", (invoice_id,))
        if not inv:
            return "N/A"
        due = datetime.strptime(inv['due_date'], "%Y-%m-%d")
        days_overdue = (datetime.now() - due).days
        if days_overdue <= 0:
            return "Aucun retard"
        elif days_overdue <= 15:
            return "Faible"
        elif days_overdue <= 30:
            return "Modéré"
        elif days_overdue <= 60:
            return "Élevé"
        else:
            return "Critique"

    def cash_flow_projection(self, months: int = 3) -> pd.DataFrame:
        today = datetime.now()
        dates = [today + timedelta(days=30*i) for i in range(months)]
        inflows = [0.0] * months
        for i, month_date in enumerate(dates):
            start = month_date.replace(day=1)
            if i == months-1:
                end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            else:
                end = (dates[i+1].replace(day=1) - timedelta(days=1))
            due_invoices = self.db.fetch_all("""
                SELECT SUM(total_ttc - IFNULL((SELECT SUM(amount) FROM payments WHERE invoice_id=id),0)) as due
                FROM invoices
                WHERE due_date BETWEEN ? AND ? AND status IN ('sent','partial')
            """, (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
            inflows[i] = due_invoices[0]['due'] or 0.0
        avg_sales = self.db.fetch_one("SELECT AVG(monthly) FROM (SELECT SUM(total_ttc) as monthly FROM invoices WHERE invoice_date >= date('now', '-3 months') GROUP BY strftime('%Y-%m', invoice_date))")[0] or 0
        for i in range(months):
            inflows[i] += avg_sales * 0.8
        df = pd.DataFrame({
            "month": [d.strftime("%Y-%m") for d in dates],
            "inflow": inflows
        })
        return df

    def comparative_analytics(self, period1: str, period2: str) -> Dict:
        def get_data(period):
            start = datetime.strptime(period + "-01", "%Y-%m-%d")
            end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            revenue = self.db.fetch_one("SELECT SUM(total_ttc) as total FROM invoices WHERE invoice_date BETWEEN ? AND ?", (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))['total'] or 0
            return {"revenue": revenue}
        return {"period1": get_data(period1), "period2": get_data(period2)}

class PaymentEngine:
    def __init__(self, db: AtlasDatabase, app):
        self.db = db
        self.app = app

    def record_payment(self, invoice_id: int, amount: float, method: str, reference: str = "", notes: str = ""):
        self.db.execute("""
            INSERT INTO payments (invoice_id, payment_date, amount, method, reference, notes)
            VALUES (?, date('now'), ?, ?, ?, ?)
        """, (invoice_id, amount, method, reference, notes))
        self.db.commit()
        self.update_invoice_status(invoice_id)
        self.app.log_action("payment_recorded", f"Facture {invoice_id} - {amount}")

    def update_invoice_status(self, invoice_id: int):
        total_paid = self.db.fetch_one("SELECT SUM(amount) as total FROM payments WHERE invoice_id = ?", (invoice_id,))
        invoice = self.db.fetch_one("SELECT total_ttc FROM invoices WHERE id = ?", (invoice_id,))
        if invoice and total_paid['total']:
            if total_paid['total'] >= invoice['total_ttc'] - 0.01:
                self.db.execute("UPDATE invoices SET status = 'paid', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (invoice_id,))
            elif total_paid['total'] > 0:
                self.db.execute("UPDATE invoices SET status = 'partial', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (invoice_id,))
        self.db.commit()

