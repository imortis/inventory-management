# Inventory Management System (StockPilot)

An **Object-Oriented Inventory Management System** built for the *Object Oriented Analysis and Design (CSE556)* case study.
A tightly coupled, procedural "god class" baseline is redesigned into a clean **four-layer architecture** using **UML 2.x**, **SOLID principles** and four **Gang-of-Four design patterns**: Factory Method, Adapter, Observer and Strategy.
The system ships with a **Flask REST backend**, a **web dashboard**, an **interactive CLI**, and an **automated test suite**.

---

## Features

| Use case | What it does |
|---|---|
| **UC1 – Register Product** | Create perishable, electronic or bulk products through `ProductFactory`, each with its own handling policy |
| **UC2 – Receive Stock** | Record inbound stock as cost batches, for FIFO valuation |
| **UC3 – Issue Stock** | Deduct stock and block any issue that would make stock negative |
| **UC4 – Low-Stock Alert & Auto-PO** | Observers send an email alert and draft a purchase order when stock reaches the reorder level |
| **UC5 – Valuation Report** | Switch between **Standard Cost** and **FIFO Batch** valuation at runtime |
| **UC6 – Sync Supplier Feed** | Import legacy supplier CSV dumps through `LegacyCSVSupplierAdapter` |

**Also included:**
- Role-based login: **Manager** and **Staff**
- Product lifecycle states: Out of Stock → In Stock → Low Stock → Reorder Pending → Discontinued
- An immutable audit trail of every transaction
- Purchase-order approval: receive or cancel a draft PO
- Data persists across server restarts

---

## Design Patterns

| Pattern | Type | Classes | Problem solved |
|---|---|---|---|
| **Factory Method** | Creational | `ProductFactory` → `PerishableItem`, `ElectronicItem`, `BulkItem` | Keeps the service from depending on concrete product constructors |
| **Adapter** | Structural | `LegacyCSVSupplierAdapter` implements `ISupplierFeed`, wraps `LegacyCSVSupplierSystem` | Turns raw supplier CSV into domain `SupplierRecord`s without changing the legacy code |
| **Observer** | Behavioural | `StockObserver` → `EmailAlertObserver`, `AutoReorderObserver` | New reactions to low stock need no edits to the stock-issue logic |
| **Strategy** | Behavioural | `ValuationStrategy` → `StandardCostValuation`, `FIFOValuation` | Swap the valuation algorithm at runtime (Open/Closed Principle) |
| **Layered Architecture** | Architectural | Presentation → Service → Domain → Data | Dependencies only point downward, so domain rules don't depend on I/O |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Presentation   Web UI (HTML/CSS/JS) · Flask REST API · CLI    │
├──────────────────────────────────────────────────────────────┤
│ Service        InventoryService · AuthService                 │
├──────────────────────────────────────────────────────────────┤
│ Domain         Product hierarchy · ProductFactory ·           │
│                StockTransaction · StockObserver ·             │
│                ValuationStrategy                              │
├──────────────────────────────────────────────────────────────┤
│ Data & Integr. InventoryRepository · ISupplierFeed ·          │
│                LegacyCSVSupplierAdapter                       │
└──────────────────────────────────────────────────────────────┘
```

### Project structure

```
├── after_ims.py            # Refactored OOAD implementation (service, domain, repository, patterns)
├── before_ims.py           # Monolithic baseline (god class), kept for comparison
├── app.py                  # Flask REST API backend
├── templates/index.html    # Web UI (single-page app)
├── static/app.js           # Frontend logic
├── static/style.css        # Styling
├── ims_cli.py              # Interactive console app
├── test_and_demo_ims.py    # 5 unit tests + UC1–UC6 demo
└── requirements.txt
```

---

## Getting Started

**You need:** Python 3.10 or newer.

```bash
git clone https://github.com/imortis/inventory-management.git
cd inventory-management
pip install -r requirements.txt
```

### Run the web app
```bash
python app.py
```
Then open **http://127.0.0.1:5000**.

| Username | Password | Role |
|---|---|---|
| `manager` | `manager123` | Full access: register, sync, valuation, purchase orders, discontinue, reset |
| `staff` | `staff123` | Receive stock, issue stock, view everything |

The app starts with demo data. Use **Reset demo data** on the dashboard, or delete the `data/` folder, to start fresh.

### Run tests and the use-case demo
```bash
python test_and_demo_ims.py
```
Expected output: `5/5 unit tests passed`. The demo prints UC1–UC6, including a Standard Cost valuation of **$653.50** and a FIFO valuation of **$659.50**.

### Run the console version
```bash
python ims_cli.py
```

---

## REST API

| Method | Endpoint | Access | Description |
|---|---|---|---|
| POST | `/api/login` · `/api/logout` | public | Start or end a session |
| GET | `/api/me` | logged in | Current user |
| GET | `/api/dashboard` | logged in | KPIs, low-stock items, recent activity |
| GET | `/api/products` · `/api/products/<sku>` | logged in | List products or show one |
| POST | `/api/products` | manager | Register a product (UC1) |
| POST | `/api/products/<sku>/receive` | logged in | Receive stock (UC2) |
| POST | `/api/products/<sku>/issue` | logged in | Issue stock and trigger alerts (UC3/UC4) |
| POST | `/api/products/<sku>/discontinue` | manager | Discontinue a product |
| GET / POST | `/api/valuation` | logged in / manager | Show the valuation or switch strategy (UC5) |
| POST | `/api/sync` | manager | Sync a supplier CSV feed (UC6) |
| GET | `/api/transactions?sku=` | logged in | Audit trail |
| GET | `/api/alerts` | logged in | Purchase orders and email alerts |
| POST | `/api/purchase-orders/<id>/receive` · `/cancel` | manager | Act on a draft purchase order |
| POST | `/api/reset` | manager | Restore the demo dataset |

**Example:**
```bash
curl -c cj -H "Content-Type: application/json" -d '{"username":"manager","password":"manager123"}' http://127.0.0.1:5000/api/login
curl -b cj -H "Content-Type: application/json" -d '{"qty":5}' http://127.0.0.1:5000/api/products/SKU-201/issue
```

---

## SOLID Compliance

- **S**ingle Responsibility: storage, use-case logic, alerting and valuation each live in their own class.
- **O**pen/Closed: add a product category, alert channel or valuation method without changing existing code.
- **L**iskov Substitution: every `Product` subclass keeps the `remove_stock()` and `get_handling_policy()` contracts.
- **I**nterface Segregation: `StockObserver`, `ValuationStrategy` and `ISupplierFeed` are small, focused interfaces.
- **D**ependency Inversion: `InventoryService` depends on abstractions, which are injected through its constructor.

## Before vs After

| Metric | Before (`before_ims.py`) | After (`after_ims.py`) |
|---|---|---|
| Classes / interfaces | 1 (god class) | 13+ cohesive classes and ABCs |
| Max cyclomatic complexity | 14 (`handle_operation`) | ≤ 4 |
| CSV and email coupling | Hard-coded | Decoupled through `ISupplierFeed` and `StockObserver` |
| Valuation extensibility | Edit `handle_operation()` | Swap a `ValuationStrategy` at runtime |
| Unit tests | 0 | 5 passing |

## Limitations & Future Work
- Data is persisted as a file snapshot; a SQLite or PostgreSQL repository adapter is planned.
- The server is single-process and uses a global lock.
- A machine-learning demand-forecasting `Strategy` is planned.

## Tech Stack
Python 3 (`abc`, `dataclasses`, `enum`, `unittest`) · Flask · vanilla HTML/CSS/JavaScript
