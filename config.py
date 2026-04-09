"""
config.py
~~~~~~~~~
Configuration globale de l'application Dataikos Atlas.
Chargée au démarrage ; paramètres persistés dans data/settings.json.
"""
from __future__ import annotations
import os
import json

class AtlasConfig:
    APP_NAME = "Dataikos Atlas"
    APP_VERSION = "3.0.0"
    COMPANY = "Dataikos"

    if '__file__' in globals():
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    else:
        BASE_DIR = os.getcwd()

    DATA_DIR = os.path.join(BASE_DIR, "data")
    CONFIG_FILE = os.path.join(DATA_DIR, "settings.json")
    DB_FILE = os.path.join(DATA_DIR, "atlas.db")
    LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.png")
    REPORTS_DIR = os.path.join(BASE_DIR, "reports")
    UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")   # pour stocker le logo

    COLORS = {
        "bg": "#EEF4FB",
        "sidebar": "#3F6FA8",
        "card": "#FFFFFF",
        "primary": "#F97316",
        "secondary": "#3F6FA8",
        "success": "#10B981",
        "warning": "#FACC15",
        "danger": "#EF4444",
        "text_dark": "#1E293B",
        "text_light": "#FFFFFF",
        "text_muted": "#64748B"
    }

    settings = {
        "company_name": "Mon Entreprise",
        "company_address": "",
        "company_phone": "",
        "company_email": "",
        "company_tax_id": "",
        "logo_path": "",
        "currency": "€",
        "vat_rate": 20.0,
        "date_format": "%d/%m/%Y",
        "language": "fr",
        "stock_alert_threshold": 10,
        "stock_method": "FIFO",
        "reorder_policy": "manual",
        "invoice_auto_numbering": True,
        "payment_terms": 30,
        "reminder_delay": 7,
        "seasonality_period": 12,
        "forecast_horizon": 30,
        "auto_optimization": True,
        "model_selection": "auto",
        "ui_theme": "Light",
        "ui_accent": "primary",
        "ui_density": "comfortable",
        "ui_font_size": 12,
        "ui_animations": True
    }

    @classmethod
    def load_settings(cls):
        os.makedirs(cls.DATA_DIR, exist_ok=True)
        os.makedirs(cls.UPLOADS_DIR, exist_ok=True)
        if os.path.exists(cls.CONFIG_FILE):
            try:
                with open(cls.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    cls.settings.update(loaded)
            except Exception as e:
                print(f"Error loading settings: {e}")

    @classmethod
    def save_settings(cls):
        try:
            with open(cls.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cls.settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving settings: {e}")

AtlasConfig.load_settings()

# ========================
# DATABASE ENGINE
# ========================
