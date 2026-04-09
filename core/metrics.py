"""
core/metrics.py
~~~~~~~~~~~~~~~
Moteur de métriques métier.
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

class BusinessMetricsEngine:
    def __init__(self, db: AtlasDatabase, app):
        self.db = db
        self.app = app

    def get_today_revenue(self):
        today = datetime.now().strftime("%Y-%m-%d")
        row = self.db.fetch_one("SELECT SUM(total_ttc) as total FROM invoices WHERE invoice_date = ? AND status != 'draft'", (today,))
        return row['total'] or 0.0

    def get_last_30_days_revenue(self):
        row = self.db.fetch_one("SELECT SUM(total_ttc) as total FROM invoices WHERE invoice_date >= date('now', '-30 days') AND status != 'draft'")
        return row['total'] or 0.0

    def get_growth_percentage(self):
        current = self.get_last_30_days_revenue()
        previous = self.db.fetch_one("SELECT SUM(total_ttc) as total FROM invoices WHERE invoice_date BETWEEN date('now', '-60 days') AND date('now', '-31 days') AND status != 'draft'")
        prev = previous['total'] or 0.0
        if prev == 0:
            return 100.0 if current > 0 else 0.0
        return ((current - prev) / prev) * 100

    def get_top_products(self, limit=5):
        return self.db.fetch_all("""
            SELECT p.id, p.name, SUM(il.quantity) as total_qty, SUM(il.total_ht) as total_revenue
            FROM invoice_lines il
            JOIN products p ON il.product_id = p.id
            JOIN invoices i ON il.invoice_id = i.id
            WHERE i.status != 'draft'
            GROUP BY p.id
            ORDER BY total_qty DESC
            LIMIT ?
        """, (limit,))

    def get_top_customers(self, limit=5):
        return self.db.fetch_all("""
            SELECT c.id, c.name, SUM(i.total_ttc) as total_spent
            FROM customers c
            JOIN invoices i ON c.id = i.customer_id
            WHERE i.status != 'draft'
            GROUP BY c.id
            ORDER BY total_spent DESC
            LIMIT ?
        """, (limit,))

    def get_inventory_stress(self) -> float:
        products = self.db.fetch_all("SELECT current_stock, min_stock, max_stock FROM products WHERE active=1")
        if not products:
            return 0
        stress = 0
        for p in products:
            if p['min_stock'] and p['current_stock'] < p['min_stock']:
                stress += (p['min_stock'] - p['current_stock']) / (p['min_stock'] or 1) * 100
            if p['max_stock'] and p['current_stock'] > p['max_stock']:
                stress += (p['current_stock'] - p['max_stock']) / (p['max_stock'] or 1) * 100
        avg_stress = stress / len(products) if products else 0
        return min(100, avg_stress)

    def get_unpaid_ratio(self) -> float:
        total_unpaid = self.db.fetch_one("SELECT SUM(total_ttc - IFNULL((SELECT SUM(amount) FROM payments WHERE invoice_id=invoices.id),0)) as due FROM invoices WHERE status IN ('sent','partial')")['due'] or 0
        total_receivable = self.db.fetch_one("SELECT SUM(total_ttc) as total FROM invoices WHERE status!='draft'")['total'] or 1
        return (total_unpaid / total_receivable) * 100

    def get_cash_flow_stability(self) -> float:
        rows = self.db.fetch_all("""
            SELECT strftime('%Y-%m', invoice_date) as month, SUM(total_ttc) as revenue
            FROM invoices
            WHERE invoice_date >= date('now', '-6 months') AND status!='draft'
            GROUP BY month
            ORDER BY month
        """)
        if len(rows) < 3:
            return 50
        revenues = [r['revenue'] or 0 for r in rows]
        std = np.std(revenues)
        mean = np.mean(revenues)
        if mean == 0:
            return 0
        cv = std / mean
        stability = max(0, 100 - cv * 100)
        return min(100, stability)

    def get_sales_volatility(self) -> float:
        rows = self.db.fetch_all("""
            SELECT invoice_date, SUM(total_ttc) as revenue
            FROM invoices
            WHERE invoice_date >= date('now', '-30 days') AND status!='draft'
            GROUP BY invoice_date
        """)
        if len(rows) < 5:
            return 50
        revenues = [r['revenue'] or 0 for r in rows]
        std = np.std(revenues)
        mean = np.mean(revenues)
        if mean == 0:
            return 0
        cv = std / mean
        volatility = min(100, cv * 100)
        return 100 - volatility

    def get_business_health_score(self) -> int:
        growth = self.get_growth_percentage()
        growth_score = min(25, max(-25, growth) + 25)

        inventory_stress = self.get_inventory_stress()
        inventory_score = max(0, 100 - inventory_stress) * 0.15

        unpaid_ratio = self.get_unpaid_ratio()
        unpaid_score = max(0, 100 - unpaid_ratio) * 0.20

        cash_flow = self.get_cash_flow_stability()
        cash_score = cash_flow * 0.20

        volatility = self.get_sales_volatility()
        vol_score = volatility * 0.10

        base = 20
        total = growth_score + inventory_score + unpaid_score + cash_score + vol_score + base
        return int(min(100, max(0, total)))

# ========================
# NARRATIVE ENGINE (inchangé)
# ========================
