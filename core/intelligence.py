"""
core/intelligence.py
~~~~~~~~~~~~~~~~~~~~
Moteurs d'intelligence et de narration automatique.
"""
from __future__ import annotations
from typing import Optional, List, Dict, Any
import numpy as np
import pandas as pd

from config   import AtlasConfig
from database import AtlasDatabase
from core.metrics        import BusinessMetricsEngine
from core.analytics      import AtlasTimeSeriesAnalyzer
from core.invoice_payment import InvoiceEngine, PaymentEngine
from core.stock          import StockEngine

class AtlasNarrativeEngine:
    def __init__(self, db: AtlasDatabase, app):
        self.db = db
        self.app = app

    def financial_summary(self, days=30) -> str:
        metrics = BusinessMetricsEngine(self.db, self.app)
        revenue = metrics.get_last_30_days_revenue()
        growth = metrics.get_growth_percentage()
        unpaid_ratio = metrics.get_unpaid_ratio()
        health = metrics.get_business_health_score()

        parts = []
        if revenue > 0:
            parts.append(f"Au cours des 30 derniers jours, le chiffre d'affaires s'élève à {revenue:.2f} {AtlasConfig.settings['currency']}.")
        else:
            parts.append("Aucune vente n'a été enregistrée sur les 30 derniers jours.")

        if growth > 10:
            parts.append(f"La croissance est remarquable, avec une augmentation de {growth:.1f}% par rapport à la période précédente, témoignant d'une dynamique commerciale positive.")
        elif growth > 0:
            parts.append(f"La croissance modérée de {growth:.1f}% indique une progression stable.")
        elif growth > -10:
            parts.append(f"L'activité est en légère baisse ({growth:.1f}%), une attention particulière aux ventes pourrait être bénéfique.")
        else:
            parts.append(f"La forte baisse de {growth:.1f}% nécessite une analyse approfondie des causes (concurrence, saisonnalité, etc.).")

        if unpaid_ratio < 10:
            parts.append("Le taux d'impayés est excellent, ce qui reflète une bonne gestion du recouvrement et une clientèle fiable.")
        elif unpaid_ratio < 20:
            parts.append("Le niveau d'impayés est modéré ; une relance proactive pourrait améliorer la trésorerie.")
        else:
            parts.append(f"Le taux d'impayés élevé ({unpaid_ratio:.1f}%) est préoccupant. Il est recommandé de revoir les conditions de paiement et de renforcer le suivi client.")

        parts.append(f"Le score de santé global de l'entreprise est de {health}/100, ce qui indique une situation {'excellente' if health>=80 else 'solide' if health>=60 else 'précaire' if health>=40 else 'critique'}.")

        return " ".join(parts)

    def stock_summary(self, days=30) -> str:
        stock_engine = self.app.stock_engine
        low_stock = stock_engine.get_low_stock_products()
        dormant = stock_engine.get_slow_moving_products(90)

        parts = []
        if low_stock:
            products = ", ".join([p['name'] for p in low_stock[:5]])
            parts.append(f"Attention : {len(low_stock)} produit(s) sont en rupture de stock imminente ({products}).")
        else:
            parts.append("Le niveau des stocks est satisfaisant, aucun produit sous seuil d'alerte.")

        if dormant:
            parts.append(f"Par ailleurs, {len(dormant)} produit(s) n'ont pas été vendus depuis 90 jours, ce qui pourrait immobiliser du capital.")
        else:
            parts.append("Tous les produits ont connu une rotation récente, signe d'une gestion dynamique.")

        return " ".join(parts)

    def forecast_narrative(self, forecast_values, conf_int, period="30 jours") -> str:
        avg_forecast = np.mean(forecast_values)
        last_known = self.db.fetch_one("SELECT SUM(total_ttc) as total FROM invoices WHERE invoice_date >= date('now', '-30 days') AND status != 'draft'")['total'] or 0
        trend = "hausse" if avg_forecast > last_known else "baisse" if avg_forecast < last_known else "stabilité"
        change_pct = ((avg_forecast - last_known) / last_known * 100) if last_known else 0

        text = f"Sur les {period} à venir, le modèle prévoit une {trend} des ventes. "
        if trend == "hausse":
            text += f"Les prévisions indiquent une augmentation de {change_pct:.1f}% par rapport à la période précédente, avec un montant moyen estimé à {avg_forecast:.2f} {AtlasConfig.settings['currency']}. "
        elif trend == "baisse":
            text += f"Une diminution de {abs(change_pct):.1f}% est anticipée, avec un montant moyen de {avg_forecast:.2f} {AtlasConfig.settings['currency']}. "
        else:
            text += f"Le niveau d'activité resterait stable autour de {avg_forecast:.2f} {AtlasConfig.settings['currency']}. "

        lower_avg = np.mean(conf_int[:,0])
        upper_avg = np.mean(conf_int[:,1])
        text += f"L'intervalle de confiance à 95% s'étend de {lower_avg:.2f} à {upper_avg:.2f} {AtlasConfig.settings['currency']}, reflétant une incertitude {'modérée' if (upper_avg-lower_avg)/avg_forecast < 0.5 else 'élevée'}."

        return text

# ========================
# TIME SERIES ENGINE (avec correction matplotlib et vérif longueur)
# ========================
class AtlasIntelligenceEngine:
    def __init__(self, db: AtlasDatabase, app):
        self.db = db
        self.app = app
        self.rules = [
            self.check_growth_decline,
            self.check_stock_reorder,
            self.check_margin_decline,
            self.check_seasonality_campaign,
            self.check_overdue_invoices,
            self.check_anomaly,
            self.check_cashflow_risk
        ]

    def check_growth_decline(self):
        months = []
        for i in range(1, 4):
            start = (datetime.now() - timedelta(days=30*i)).strftime("%Y-%m-%d")
            end = (datetime.now() - timedelta(days=30*(i-1))).strftime("%Y-%m-%d")
            row = self.db.fetch_one("SELECT SUM(total_ttc) as total FROM invoices WHERE invoice_date BETWEEN ? AND ? AND status != 'draft'", (start, end))
            months.append(row['total'] or 0.0)
        if len(months) == 3 and months[0] > months[1] > months[2]:
            return "📉 Croissance en baisse depuis 3 mois. Analysez les causes."
        return None

    def check_stock_reorder(self):
        low_stock = self.db.fetch_all("SELECT * FROM products WHERE current_stock <= min_stock AND min_stock > 0")
        if low_stock:
            products = ", ".join([p['name'] for p in low_stock[:3]])
            if len(low_stock) > 3:
                products += f" et {len(low_stock)-3} autres"
            return f"📦 Réapprovisionnement nécessaire : {products}"
        return None

    def check_margin_decline(self):
        avg_margin_now = self.db.fetch_one("""
            SELECT AVG(il.unit_price - p.cost_price) as margin
            FROM invoice_lines il
            JOIN products p ON il.product_id = p.id
            JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_date >= date('now', '-30 days')
        """)['margin'] or 0
        avg_margin_before = self.db.fetch_one("""
            SELECT AVG(il.unit_price - p.cost_price) as margin
            FROM invoice_lines il
            JOIN products p ON il.product_id = p.id
            JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_date BETWEEN date('now', '-60 days') AND date('now', '-31 days')
        """)['margin'] or 0
        if avg_margin_before > 0 and avg_margin_now < avg_margin_before * 0.9:
            return f"⚠️ Marge en baisse de {((avg_margin_before-avg_margin_now)/avg_margin_before*100):.1f}%"
        return None

    def check_seasonality_campaign(self):
        last_7d = self.db.fetch_one("SELECT SUM(total_ttc) as total FROM invoices WHERE invoice_date >= date('now', '-7 days')")['total'] or 0
        prev_7d = self.db.fetch_one("SELECT SUM(total_ttc) as total FROM invoices WHERE invoice_date BETWEEN date('now', '-14 days') AND date('now', '-8 days')")['total'] or 0
        if prev_7d > 0 and last_7d > prev_7d * 1.5:
            return f"🔥 Forte hausse des ventes cette semaine (+{((last_7d-prev_7d)/prev_7d*100):.0f}%). Campagne marketing ?"
        return None

    def check_overdue_invoices(self):
        overdue = self.app.invoice_engine.get_overdue_invoices()
        if overdue:
            count = len(overdue)
            total_due = sum(inv['total_ttc'] for inv in overdue)
            return f"⚠️ {count} facture(s) en retard pour un total de {total_due:.2f} {AtlasConfig.settings['currency']}. Relance conseillée."
        return None

    def check_anomaly(self):
        rows = self.db.fetch_all("""
            SELECT invoice_date, SUM(total_ttc) as revenue
            FROM invoices
            WHERE invoice_date >= date('now', '-60 days') AND status != 'draft'
            GROUP BY invoice_date
            ORDER BY invoice_date
        """)
        if len(rows) < 10:
            return None
        df = pd.DataFrame([(r['invoice_date'], r['revenue'] or 0) for r in rows], columns=['date','revenue'])
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df = df.asfreq('D').fillna(0)
        rolling_mean = df['revenue'].rolling(window=7, min_periods=4).mean()
        rolling_std = df['revenue'].rolling(window=7, min_periods=4).std()
        latest = df['revenue'].iloc[-1]
        if len(rolling_mean) > 0:
            mean = rolling_mean.iloc[-1]
            std = rolling_std.iloc[-1]
            if std > 0 and (latest > mean + 3*std or latest < mean - 3*std):
                return f"🚨 Anomalie détectée : vente du {df.index[-1].strftime('%d/%m')} à {latest:.0f} {AtlasConfig.settings['currency']} (moyenne {mean:.0f} {AtlasConfig.settings['currency']})."
        return None

    def check_cashflow_risk(self):
        avg_monthly = self.db.fetch_one("SELECT AVG(monthly) FROM (SELECT SUM(total_ttc) as monthly FROM invoices WHERE invoice_date >= date('now', '-3 months') GROUP BY strftime('%Y-%m', invoice_date))")[0] or 1
        unpaid = self.db.fetch_one("SELECT SUM(total_ttc - IFNULL((SELECT SUM(amount) FROM payments WHERE invoice_id=invoices.id),0)) as due FROM invoices WHERE status IN ('sent','partial')")['due'] or 0
        if unpaid > 0.3 * avg_monthly:
            return f"⚠️ Risque de trésorerie : {unpaid:.0f} {AtlasConfig.settings['currency']} de factures impayées (>{0.3*avg_monthly:.0f} {AtlasConfig.settings['currency']})."
        return None

    def generate_daily_insight(self) -> str:
        for rule in self.rules:
            insight = rule()
            if insight:
                return insight
        return "✅ Tout va bien. Aucun insight particulier aujourd'hui."

    def smart_restock_recommendation(self, product_id: int) -> str:
        sales_30d = self.db.fetch_one("""
            SELECT SUM(quantity) as qty FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            WHERE il.product_id=? AND i.invoice_date >= date('now', '-30 days')
        """, (product_id,))['qty'] or 0
        avg_daily = sales_30d / 30
        lead_time = 7
        forecast_demand = avg_daily * lead_time
        current_stock = self.db.fetch_one("SELECT current_stock FROM products WHERE id=?", (product_id,))['current_stock'] or 0
        if current_stock < forecast_demand:
            return f"Stock actuel ({current_stock}) insuffisant pour couvrir la demande prévue ({forecast_demand:.0f}) sur {lead_time} jours. Recommandation : commander {forecast_demand - current_stock:.0f} unités."
        else:
            return f"Stock suffisant pour {lead_time} jours ({current_stock} > {forecast_demand:.0f})."

# ========================
# COMMAND CENTER DASHBOARD (avec scrollbar)
# ========================
