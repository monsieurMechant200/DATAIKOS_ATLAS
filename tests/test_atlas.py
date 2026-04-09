"""
tests/test_atlas.py
~~~~~~~~~~~~~~~~~~~
Tests unitaires pour Dataikos Atlas.
Lancer avec :  python main.py --test
          ou : python -m pytest tests/
"""
from __future__ import annotations
import os
import sys
import hashlib
import sqlite3
import tempfile
import unittest

# Ajout du répertoire racine au path pour les imports relatifs
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config      import AtlasConfig
from database    import AtlasDatabase
from core.stock          import StockEngine
from core.invoice_payment import InvoiceEngine

class TestAtlas(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        AtlasConfig.DB_FILE = self.temp_db.name
        self.db = AtlasDatabase()
        self.db.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
                        ("test", hashlib.sha256("test".encode()).hexdigest(), "Test User", "manager"))
        self.user_id = self.db.cursor.lastrowid
        self.app = type('App', (), {'db': self.db, 'current_user': {'id': self.user_id}})()
        self.app.log_action = lambda a, d: None

    def tearDown(self):
        self.db.close()
        os.unlink(self.temp_db.name)

    def test_product_crud(self):
        self.db.execute("INSERT INTO products (code, name, unit_price) VALUES (?, ?, ?)",
                        ("TEST001", "Produit test", 10.0))
        self.db.commit()
        prod = self.db.fetch_one("SELECT * FROM products WHERE code='TEST001'")
        self.assertIsNotNone(prod)
        self.assertEqual(prod['name'], "Produit test")

    def test_stock_movement(self):
        self.db.execute("INSERT INTO products (code, name, unit_price, current_stock) VALUES (?, ?, ?, ?)",
                        ("STOCK001", "Test Stock", 5.0, 10))
        self.db.commit()
        prod_id = self.db.cursor.lastrowid

        engine = StockEngine(self.db, self.app)
        new_stock = engine.add_movement(prod_id, 'out', 3, user_id=self.user_id)
        self.assertEqual(new_stock, 7)

        mov = self.db.fetch_one("SELECT * FROM stock_movements WHERE product_id=?", (prod_id,))
        self.assertIsNotNone(mov)
        self.assertEqual(mov['quantity'], 3)

    def test_invoice_creation(self):
        self.db.execute("INSERT INTO customers (code, name) VALUES (?, ?)", ("CLI001", "Client Test"))
        self.db.commit()
        cust_id = self.db.cursor.lastrowid
        self.db.execute("INSERT INTO products (code, name, unit_price, current_stock) VALUES (?, ?, ?, ?)",
                        ("PROD001", "Article test", 10.0, 5))
        prod_id = self.db.cursor.lastrowid

        engine = InvoiceEngine(self.db, self.app)
        lines = [{'product_id': prod_id, 'description': 'Article 1', 'quantity': 2, 'unit_price': 10.0, 'tax_rate': 20.0}]
        invoice_id = engine.create_invoice(cust_id, lines)

        inv = self.db.fetch_one("SELECT * FROM invoices WHERE id=?", (invoice_id,))
        self.assertIsNotNone(inv)
        self.assertEqual(inv['total_ht'], 20.0)
        self.assertEqual(inv['total_tax'], 4.0)
        self.assertEqual(inv['total_ttc'], 24.0)

        prod = self.db.fetch_one("SELECT current_stock FROM products WHERE id=?", (prod_id,))
        self.assertEqual(prod['current_stock'], 3)

    def test_user_creation(self):
        self.db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                        ("newuser", "hash", "commercial"))
        self.db.commit()
        user = self.db.fetch_one("SELECT * FROM users WHERE username='newuser'")
        self.assertIsNotNone(user)
        self.assertEqual(user['role'], "commercial")

    def test_activity_log(self):
        self.app.log_action = lambda a, d: self.db.execute("INSERT INTO activity_log (user_id, action, details) VALUES (?, ?, ?)",
                                                           (self.user_id, a, d)) or self.db.commit()
        self.app.log_action("test_action", "detail")
        log = self.db.fetch_one("SELECT * FROM activity_log WHERE user_id=?", (self.user_id,))
        self.assertIsNotNone(log)
        self.assertEqual(log['action'], "test_action")

# ========================
# MAIN ENTRY POINT
# ========================
