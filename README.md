# 🧭 Dataikos Atlas

> **Smart Enterprise Intelligence Desktop** — Application de gestion d'entreprise tout-en-un, construite avec Python et CustomTkinter.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)
![CustomTkinter](https://img.shields.io/badge/CustomTkinter-5.2%2B-informational)
![SQLite](https://img.shields.io/badge/Base%20de%20données-SQLite-lightgrey?logo=sqlite)
![License](https://img.shields.io/badge/All-Rights-Reserved)
![Version](https://img.shields.io/badge/Version-3.0.0-orange)

---

## Sommaire

- [Présentation](#-présentation)
- [Fonctionnalités](#-fonctionnalités)
- [Architecture](#-architecture)
- [Installation](#-installation)
- [Lancement](#-lancement)
- [Rôles utilisateurs](#-rôles-utilisateurs)
- [Structure du projet](#-structure-du-projet)
- [Tests](#-tests)
- [Dépendances](#-dépendances)
- [Contribuer](#-contribuer)

---

## Présentation

**Dataikos Atlas** est une application de bureau conçue pour les PME souhaitant centraliser leur gestion opérationnelle sans dépendre d'un service cloud. Elle fonctionne entièrement en local grâce à une base de données SQLite embarquée.

Elle couvre en un seul outil :

- La gestion des **stocks** (mouvements, alertes, FIFO)
- La **facturation** et le suivi des **paiements**
- Le **CRM** (portefeuille clients)
- L'**analytique prédictive** (ARIMA / SARIMAX)
- La **narration automatique** des indicateurs métier par IA
- La **génération de rapports PDF**

---

## Fonctionnalités

### Tableau de bord
- Vue synthétique des KPIs (chiffre d'affaires, stock, impayés)
- Narration automatique des tendances via `AtlasNarrativeEngine`
- Alertes de stock et factures en retard en temps réel

### Gestion des stocks
- Fiche produit complète (code, catégorie, prix, seuils min/max)
- Mouvements d'entrée / sortie / ajustement avec historique
- Méthode de valorisation **FIFO**
- Alertes de rupture configurables
- Export CSV

### Finance & Facturation
- Création et suivi de factures (brouillon → validée → payée)
- Gestion des paiements partiels
- Calcul automatique HT / TVA / TTC
- Relances automatiques selon délai paramétrable
- **Export PDF** des factures (via ReportLab)

### CRM Clients
- Fiche client complète (coordonnées, conditions de paiement, plafond de crédit)
- Historique des factures par client
- Segmentation et recherche rapide

### Analytics & Prévisions
- Analyse de séries temporelles (CA, stocks, paiements)
- Tests de stationnarité (ADF, KPSS)
- Modèles **ARIMA** et **SARIMAX** avec sélection automatique
- Décomposition saisonnière
- Visualisation interactive (Matplotlib embarqué)

### Intelligence & Narration
- `AtlasIntelligenceEngine` : génération de résumés financiers automatiques
- `AtlasNarrativeEngine` : traduction des métriques en langage naturel

### Gestion des utilisateurs
- Authentification sécurisée (SHA-256)
- 4 rôles : `admin`, `manager`, `commercial`, `stock_manager`
- Journal d'activité complet (qui a fait quoi, quand)

### Paramètres
- Personnalisation de l'entreprise (nom, logo, SIRET, TVA)
- Thème visuel (clair / sombre)
- Paramètres de stock, facturation, prévisions

---

## Architecture

Le projet suit une architecture **MVC modulaire** strictement séparée en couches :

```
dataikos_atlas/
│
├── main.py                     # Point d'entrée
├── config.py                   # Configuration globale (AtlasConfig)
├── requirements.txt
│
├── models/                     # DataClasses (entités métier)
│   └── entities.py             # Product, Customer, Invoice, Payment…
│
├── database/                   # Accès données
│   └── db_manager.py           # AtlasDatabase (SQLite)
│
├── core/                       # Moteurs métier (Business Logic)
│   ├── stock.py                # StockEngine
│   ├── invoice_payment.py      # InvoiceEngine, PaymentEngine
│   ├── metrics.py              # BusinessMetricsEngine
│   ├── analytics.py            # AtlasTimeSeriesAnalyzer
│   └── intelligence.py         # AtlasIntelligenceEngine, AtlasNarrativeEngine
│
├── gui/                        # Interface graphique (CustomTkinter)
│   ├── app.py                  # Fenêtre principale
│   ├── login.py                # Fenêtre de connexion
│   ├── sidebar.py              # Barre de navigation
│   └── views/                  # Écrans
│       ├── dashboard.py
│       ├── stock_view.py
│       ├── finance_view.py
│       ├── customer_view.py
│       ├── analytics_view.py
│       ├── activity_view.py
│       ├── users_view.py
│       └── settings_view.py
│
├── utils/
│   └── patches.py              # Compatibilité hashlib / warnings
│
└── tests/
    └── test_atlas.py           # Tests unitaires (unittest)
```

---

## Installation

### Prérequis

- Python **3.8 ou supérieur**
- `pip`

### Étapes

```bash
# 1. Cloner le dépôt
git clone https://github.com/votre-username/dataikos-atlas.git
cd dataikos-atlas

# 2. (Recommandé) Créer un environnement virtuel
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Lancer l'application
cd dataikos_atlas
python main.py
```

> **Note Windows / Anaconda :** si tu utilises Anaconda, l'environnement de base suffit. Assure-toi que `customtkinter` et `reportlab` sont installés :
> ```bash
> pip install customtkinter reportlab tkcalendar
> ```

### Première connexion

Au premier lancement, un compte administrateur est créé automatiquement :

| Champ | Valeur |
|-------|--------|
| Identifiant | `admin` |
| Mot de passe | `admin` |

⚠️ **Changez ce mot de passe dès la première connexion** dans *Paramètres → Gestion des utilisateurs*.

---

## Lancement

```bash
cd dataikos_atlas

# Lancer l'application
python main.py

# Lancer les tests unitaires
python main.py --test
```

---

##  Rôles utilisateurs

| Rôle | Dashboard | Stock | Factures | Clients | Analytics | Utilisateurs | Paramètres |
|------|:---------:|:-----:|:--------:|:-------:|:---------:|:------------:|:----------:|
| `admin` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `manager` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `commercial` | ✅ | 👁️ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `stock_manager` | ✅ | ✅ | 👁️ | 👁️ | ✅ | ❌ | ❌ |

> 👁️ = lecture seule

---

## Tests

```bash
cd dataikos_atlas
python main.py --test
```

La suite couvre :

- CRUD produits
- Mouvements de stock
- Création et calcul de factures (HT/TVA/TTC)
- Création d'utilisateurs
- Journal d'activité

---

## Dépendances

| Package | Usage |
|---------|-------|
| `customtkinter` | Interface graphique moderne |
| `Pillow` | Gestion des images / logo |
| `pandas` | Manipulation des données |
| `numpy` | Calculs numériques |
| `matplotlib` | Graphiques embarqués |
| `statsmodels` | Modèles ARIMA / SARIMAX / tests stats |
| `reportlab` | Génération de PDF |
| `tkcalendar` | Sélecteur de date (optionnel) |

---

## Configuration

Les paramètres sont persistés dans `data/settings.json` et modifiables depuis l'interface. Les principaux réglages :

```json
{
  "company_name": "Mon Entreprise",
  "currency": "€",
  "vat_rate": 20.0,
  "stock_alert_threshold": 10,
  "stock_method": "FIFO",
  "payment_terms": 30,
  "forecast_horizon": 30,
  "ui_theme": "Light"
}
```

---

## Contribuer

Les contributions sont les bienvenues !

```bash
# Fork → clone → nouvelle branche
git checkout -b feature/ma-fonctionnalite

# Après modifications
git commit -m "feat: description claire"
git push origin feature/ma-fonctionnalite
# → Ouvrir une Pull Request
```

Conventions de commit recommandées : `feat:`, `fix:`, `refactor:`, `docs:`, `test:`

---

## Licence

Ce projet est distribué sous licence **All Rights Reserved**. Voir le fichier [LICENSE](LICENSE) pour les détails.

---

<p align="center">
  Développé par <strong>David Meilleur Aat Ndongo</strong> · <em>Smart Enterprise Intelligence</em>
</p>
