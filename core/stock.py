"""
core/stock.py
~~~~~~~~~~~~~
Moteur de gestion des stocks.
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

class StockEngine:
    def __init__(self, db: AtlasDatabase, app):
        self.db = db
        self.app = app

    def add_movement(self, product_id: int, movement_type: str, quantity: int,
                     unit_price: float = None, reason: str = "", reference: str = "", user_id: int = None):
        if quantity <= 0:
            raise ValueError("La quantité doit être positive")
        product = self.db.fetch_one("SELECT * FROM products WHERE id = ?", (product_id,))
        if not product:
            raise ValueError("Produit introuvable")

        movement_type = movement_type.lower()
        if movement_type not in ('in', 'out', 'adjustment'):
            raise ValueError("Type de mouvement invalide")

        if movement_type == 'in':
            new_stock = product['current_stock'] + quantity
        elif movement_type == 'out':
            if product['current_stock'] < quantity:
                raise ValueError("Stock insuffisant")
            new_stock = product['current_stock'] - quantity
        else:
            new_stock = quantity

        self.db.execute("""
            INSERT INTO stock_movements (product_id, movement_type, quantity, unit_price, reason, reference, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (product_id, movement_type, quantity, unit_price, reason, reference, user_id))

        self.db.execute("UPDATE products SET current_stock = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_stock, product_id))
        self.db.commit()

        self.app.log_action("stock_movement", f"Produit {product_id} - {movement_type} - {quantity}")
        return new_stock

    def get_movements(self, product_id: Optional[int] = None, days: int = 30):
        query = "SELECT * FROM stock_movements WHERE created_at >= date('now', ?)"
        params = (f'-{days} days',)
        if product_id:
            query += " AND product_id = ?"
            params += (product_id,)
        query += " ORDER BY created_at DESC"
        return self.db.fetch_all(query, params)

    def get_movement_summary(self, days: int = 30):
        rows = self.db.fetch_all("""
            SELECT date(created_at) as day,
                   SUM(CASE WHEN movement_type='in' THEN quantity ELSE 0 END) as total_in,
                   SUM(CASE WHEN movement_type='out' THEN quantity ELSE 0 END) as total_out
            FROM stock_movements
            WHERE created_at >= date('now', ?)
            GROUP BY day
            ORDER BY day
        """, (f'-{days} days',))
        return rows

    def get_low_stock_products(self):
        threshold = AtlasConfig.settings.get("stock_alert_threshold", 10)
        return self.db.fetch_all("SELECT * FROM products WHERE current_stock <= min_stock AND min_stock > 0 AND active = 1")

    def get_top_margin_products(self, limit=5):
        return self.db.fetch_all("""
            SELECT *, (unit_price - cost_price) as margin 
            FROM products 
            WHERE cost_price > 0 AND active = 1 
            ORDER BY margin DESC 
            LIMIT ?
        """, (limit,))

    def get_slow_moving_products(self, days=90):
        return self.db.fetch_all("""
            SELECT p.* FROM products p
            LEFT JOIN stock_movements sm ON p.id = sm.product_id
            WHERE p.active = 1
            GROUP BY p.id
            HAVING MAX(sm.created_at) < date('now', ?) OR MAX(sm.created_at) IS NULL
        """, (f'-{days} days',))

    def product_performance_score(self, product_id: int) -> float:
        prod = self.db.fetch_one("SELECT * FROM products WHERE id=?", (product_id,))
        if not prod:
            return 0
        score = 0
        if prod['cost_price'] and prod['unit_price']:
            margin_pct = (prod['unit_price'] - prod['cost_price']) / prod['unit_price'] * 100
            score += min(40, margin_pct * 2)
        sales_qty = self.db.fetch_one("""
            SELECT SUM(quantity) as qty FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            WHERE il.product_id=? AND i.invoice_date >= date('now', '-90 days')
        """, (product_id,))
        sold = sales_qty['qty'] or 0
        avg_stock = prod['current_stock'] or 1
        rotation = sold / avg_stock
        score += min(30, rotation * 10)
        last_month = self.db.fetch_one("""
            SELECT SUM(quantity) as qty FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            WHERE il.product_id=? AND i.invoice_date >= date('now', '-30 days')
        """, (product_id,))['qty'] or 0
        prev_month = self.db.fetch_one("""
            SELECT SUM(quantity) as qty FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            WHERE il.product_id=? AND i.invoice_date BETWEEN date('now', '-60 days') AND date('now', '-31 days')
        """, (product_id,))['qty'] or 0
        if prev_month > 0:
            growth = (last_month - prev_month) / prev_month * 100
            score += min(30, max(-30, growth) + 30)
        else:
            score += 15
        return min(100, max(0, score))

    def get_dormant_products(self, days=90):
        return self.db.fetch_all("""
            SELECT p.* FROM products p
            LEFT JOIN invoice_lines il ON p.id = il.product_id
            LEFT JOIN invoices i ON il.invoice_id = i.id AND i.invoice_date >= date('now', ?)
            WHERE i.id IS NULL AND p.active = 1
        """, (f'-{days} days',))

    def restock_simulation(self, product_id: int, forecast_qty: int) -> Dict:
        prod = self.db.fetch_one("SELECT * FROM products WHERE id=?", (product_id,))
        if not prod:
            return {}
        cost = prod['cost_price'] or 0
        price = prod['unit_price'] or 0
        margin = price - cost
        profit = margin * forecast_qty
        storage_cost = forecast_qty * 0.1
        return {
            "product": prod['name'],
            "forecast_qty": forecast_qty,
            "expected_profit": profit,
            "storage_cost": storage_cost,
            "net_gain": profit - storage_cost
        }

    def forecast_based_alert(self, product_id: int, forecast_qty: int) -> str:
        prod = self.db.fetch_one("SELECT current_stock FROM products WHERE id=?", (product_id,))
        if prod and prod['current_stock'] < forecast_qty:
            return f"⚠️ Stock actuel ({prod['current_stock']}) inférieur à la demande prévue ({forecast_qty}). Réapprovisionnement recommandé."
        return ""

