"""
database/db_manager.py
~~~~~~~~~~~~~~~~~~~~~~
Classe AtlasDatabase : connexion SQLite, création des tables,
opérations CRUD bas niveau.
"""
from __future__ import annotations
import hashlib
import sqlite3
from typing import Optional, List

from config import AtlasConfig

class AtlasDatabase:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.connect()
        self.create_tables()
        self.create_default_admin()

    def connect(self):
        self.conn = sqlite3.connect(AtlasConfig.DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

    def close(self):
        if self.conn:
            self.conn.close()

    def commit(self):
        if self.conn:
            self.conn.commit()

    def execute(self, query: str, params: tuple = ()):
        try:
            self.cursor.execute(query, params)
            return self.cursor
        except sqlite3.Error as e:
            print(f"DB Error: {e}")
            raise

    def fetch_all(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        self.execute(query, params)
        return self.cursor.fetchall()

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        self.execute(query, params)
        return self.cursor.fetchone()

    def create_tables(self):
        self.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                unit_price REAL NOT NULL,
                cost_price REAL,
                current_stock INTEGER DEFAULT 0,
                min_stock INTEGER DEFAULT 0,
                max_stock INTEGER,
                location TEXT,
                active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.execute("CREATE INDEX IF NOT EXISTS idx_products_code ON products(code)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")

        self.execute("""
            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                movement_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL,
                reason TEXT,
                reference TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER,
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """)
        self.execute("CREATE INDEX IF NOT EXISTS idx_stock_movements_product ON stock_movements(product_id)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_stock_movements_created ON stock_movements(created_at)")

        self.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                address TEXT,
                city TEXT,
                postal_code TEXT,
                country TEXT,
                tax_id TEXT,
                payment_terms INTEGER,
                credit_limit REAL,
                active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.execute("CREATE INDEX IF NOT EXISTS idx_customers_code ON customers(code)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name)")

        self.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT UNIQUE NOT NULL,
                customer_id INTEGER NOT NULL,
                invoice_date DATE NOT NULL,
                due_date DATE NOT NULL,
                total_ht REAL NOT NULL,
                total_tax REAL NOT NULL,
                total_ttc REAL NOT NULL,
                status TEXT DEFAULT 'draft',
                payment_method TEXT,
                notes TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id),
                FOREIGN KEY(created_by) REFERENCES users(id)
            )
        """)
        self.execute("CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)")

        self.execute("""
            CREATE TABLE IF NOT EXISTS invoice_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                product_id INTEGER,
                description TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                tax_rate REAL DEFAULT 0,
                discount REAL DEFAULT 0,
                total_ht REAL NOT NULL,
                FOREIGN KEY(invoice_id) REFERENCES invoices(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """)

        self.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                payment_date DATE NOT NULL,
                amount REAL NOT NULL,
                method TEXT,
                reference TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(invoice_id) REFERENCES invoices(id)
            )
        """)

        self.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                email TEXT,
                role TEXT DEFAULT 'manager',
                active BOOLEAN DEFAULT 1,
                last_login TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")

        self.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT NOT NULL,
                details TEXT,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        self.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_user ON activity_log(user_id)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_created ON activity_log(created_at)")

        self.commit()

    def create_default_admin(self):
        count = self.fetch_one("SELECT COUNT(*) as cnt FROM users")
        if count['cnt'] == 0:
            password_hash = hashlib.sha256("admin".encode()).hexdigest()
            self.execute(
                "INSERT INTO users (username, password_hash, full_name, role, active) VALUES (?, ?, ?, ?, ?)",
                ("admin", password_hash, "Administrateur", "admin", 1)
            )
            self.commit()

