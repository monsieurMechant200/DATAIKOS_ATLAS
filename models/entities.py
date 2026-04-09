"""
models/entities.py
~~~~~~~~~~~~~~~~~~
DataClasses représentant les entités métier de Dataikos Atlas.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

class Product:
    id: Optional[int] = None
    code: str = ""
    name: str = ""
    description: str = ""
    category: str = ""
    unit_price: float = 0.0
    cost_price: float = 0.0
    current_stock: int = 0
    min_stock: int = 0
    max_stock: Optional[int] = None
    location: str = ""
    active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

@dataclass
class Customer:
    id: Optional[int] = None
    code: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    postal_code: str = ""
    country: str = ""
    tax_id: str = ""
    payment_terms: int = 30
    credit_limit: float = 0.0
    active: bool = True
    created_at: Optional[str] = None

@dataclass
class Invoice:
    id: Optional[int] = None
    invoice_number: str = ""
    customer_id: int = 0
    invoice_date: str = ""
    due_date: str = ""
    total_ht: float = 0.0
    total_tax: float = 0.0
    total_ttc: float = 0.0
    status: str = "draft"
    payment_method: str = ""
    notes: str = ""
    created_by: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

@dataclass
class InvoiceLine:
    id: Optional[int] = None
    invoice_id: int = 0
    product_id: Optional[int] = None
    description: str = ""
    quantity: int = 1
    unit_price: float = 0.0
    tax_rate: float = 0.0
    discount: float = 0.0
    total_ht: float = 0.0

@dataclass
class Payment:
    id: Optional[int] = None
    invoice_id: int = 0
    payment_date: str = ""
    amount: float = 0.0
    method: str = ""
    reference: str = ""
    notes: str = ""
    created_at: Optional[str] = None

@dataclass
class StockMovement:
    id: Optional[int] = None
    product_id: int = 0
    movement_type: str = ""
    quantity: int = 0
    unit_price: Optional[float] = None
    reason: str = ""
    reference: str = ""
    created_at: Optional[str] = None
    user_id: Optional[int] = None

@dataclass
class User:
    id: Optional[int] = None
    username: str = ""
    password_hash: str = ""
    full_name: str = ""
    email: str = ""
    role: str = "manager"
    active: bool = True
    last_login: Optional[str] = None
    created_at: Optional[str] = None

# ========================
# BUSINESS ENGINES (inchangés)
# ========================
