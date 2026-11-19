"""
app.py - Web backend (Flask REST API) for the Inventory Management System.

Presentation layer for the web: it only translates HTTP <-> InventoryService calls.
All business rules stay in after_ims.py (Service / Domain / Repository layers).

Run:   python app.py      then open http://127.0.0.1:5000
Logins: manager / manager123   staff / staff123
"""
import os
import pickle
import secrets
import threading
from functools import wraps

from flask import Flask, jsonify, render_template, request, session

from after_ims import (
    AuthService, AutoReorderObserver, EmailAlertObserver, FIFOValuation, InsufficientStockError,
    InventoryRepository, InventoryService, LegacyCSVSupplierAdapter, LegacyCSVSupplierSystem,
    ProductFactory, ProductState, StandardCostValuation,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "ims_state.pkl")
SECRET_FILE = os.path.join(DATA_DIR, "secret.key")
os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__)
if not os.path.exists(SECRET_FILE):
    with open(SECRET_FILE, "w") as f:
        f.write(secrets.token_hex(32))
with open(SECRET_FILE) as f:
    app.secret_key = f.read().strip()

LOCK = threading.RLock()
STRATEGIES = {"standard": StandardCostValuation, "fifo": FIFOValuation}


class SessionAuth:
    """Adapts the per-request Flask session to the AuthService.require() contract."""

    def __init__(self, users: AuthService):
        self.users = users

    def require(self, *roles):
        user, role = session.get("user"), session.get("role")
        if not user:
            raise PermissionError("Not authenticated")
        if roles and role not in roles:
            raise PermissionError(f"Role '{role}' is not permitted to perform this action")
        return user


class AppState:
    """Everything that is persisted between server restarts."""

    def __init__(self):
        self.users = AuthService()
        self.repo = InventoryRepository()
        self.email = EmailAlertObserver()
        self.auto_po = AutoReorderObserver()
        self.strategy_key = "standard"


def build_service(st: AppState) -> InventoryService:
    svc = InventoryService(st.repo, STRATEGIES[st.strategy_key](), SessionAuth(st.users))
    svc.attach(st.email)
    svc.attach(st.auto_po)
    return svc


def seed(st: AppState) -> None:
    """Demo data matching the case-study report (valuation $653.50 / $659.50)."""
    svc = InventoryService(st.repo)  # system user, no auth needed for seeding
    svc.attach(st.email)
    svc.attach(st.auto_po)
    svc.register_product("perishable", "SKU-101", "Fresh Milk", 2.50, 15, expiry_date="2026-12-05")
    svc.register_product("electronic", "SKU-201", "Barcode Scanner", 45.00, 5, warranty_months=24)
    svc.register_product("bulk", "SKU-301", "Portland Cement", 9.10, 8, unit_measure="bag")
    for sku, qty, cost in [("SKU-101", 30, 2.40), ("SKU-101", 20, 2.60),
                           ("SKU-201", 10, 45.30), ("SKU-301", 10, 9.28)]:
        svc.receive_stock(sku, qty, cost)
    svc.sync_supplier_feed(LegacyCSVSupplierAdapter(LegacyCSVSupplierSystem()))
    svc.issue_stock("SKU-101", 38)


def load_state() -> AppState:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    st = AppState()
    seed(st)
    return st


def save_state() -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(STATE, f)
    os.replace(tmp, STATE_FILE)


STATE = load_state()
save_state()


# ------------------------------- helpers ---------------------------------

def product_json(p):
    extra = {}
    for attr in ("expiry_date", "warranty_months", "unit_measure"):
        if hasattr(p, attr):
            extra[attr] = getattr(p, attr)
    return {
        "sku": p.sku, "name": p.name, "category": p.category, "type": type(p).__name__,
        "quantity": p.quantity, "unit_price": p.unit_price, "reorder_level": p.reorder_level,
        "stock_value": round(p.quantity * p.unit_price, 2), "state": p.state.value,
        "needs_reorder": p.needs_reorder(), "handling_policy": p.get_handling_policy(),
        "details": p.details(), "extra": extra,
        "batches": [{"qty": b.qty, "unit_cost": b.unit_cost} for b in STATE.repo.get_batches(p.sku)],
    }


def tx_json(t):
    return {"id": t.tx_id, "type": t.tx_type.value, "sku": t.sku, "qty": t.qty,
            "unit_cost": t.unit_cost, "user": t.user, "timestamp": t.timestamp}


def api(roles=None, mutates=False):
    """Decorator: auth check, locking, persistence and uniform error handling."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            with LOCK:
                try:
                    if roles is not None:
                        SessionAuth(STATE.users).require(*roles)
                    result = fn(build_service(STATE), *a, **kw)
                    if mutates:
                        save_state()
                    return result
                except PermissionError as e:
                    code = 401 if "Not authenticated" in str(e) else 403
                    return jsonify(error=str(e)), code
                except KeyError as e:
                    return jsonify(error=str(e).strip("'\"")), 404
                except (ValueError, InsufficientStockError, TypeError) as e:
                    return jsonify(error=str(e)), 400
        return wrapper
    return deco


def body():
    return request.get_json(silent=True) or {}


def num(d, key, cast, required=True):
    v = d.get(key)
    if v in (None, ""):
        if required:
            raise ValueError(f"'{key}' is required")
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        raise ValueError(f"'{key}' must be a number")


# -------------------------------- routes ---------------------------------

@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/login")
def login():
    d = body()
    with LOCK:
        users = STATE.users
        if users.login(d.get("username", ""), d.get("password", "")):
            session["user"], session["role"] = users.current_user, users.current_role
            users.logout()
            return jsonify(user=session["user"], role=session["role"])
    return jsonify(error="Invalid username or password"), 401


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    if not session.get("user"):
        return jsonify(error="Not authenticated"), 401
    return jsonify(user=session["user"], role=session["role"])


@app.get("/api/dashboard")
@api(roles=())
def dashboard(svc):
    products = svc.list_products()
    states = {s.value: 0 for s in ProductState}
    for p in products:
        states[p.state.value] += 1
    by_cat = {}
    for p in products:
        c = by_cat.setdefault(p.category, {"count": 0, "units": 0, "value": 0.0})
        c["count"] += 1
        c["units"] += p.quantity
        c["value"] = round(c["value"] + p.quantity * p.unit_price, 2)
    return jsonify(
        total_products=len(products),
        total_units=sum(p.quantity for p in products),
        low_stock=[product_json(p) for p in svc.low_stock_products()],
        states=states, by_category=by_cat,
        valuation={"active": svc.valuation_strategy.name, "active_key": STATE.strategy_key,
                   "standard": StandardCostValuation().valuate(STATE.repo),
                   "fifo": FIFOValuation().valuate(STATE.repo)},
        open_pos=sum(1 for po in STATE.auto_po.purchase_orders if po.status == "DRAFT"),
        recent=[tx_json(t) for t in reversed(svc.audit_trail()[-8:])],
        products=[{"sku": p.sku, "name": p.name, "quantity": p.quantity,
                   "reorder_level": p.reorder_level} for p in products],
    )


@app.get("/api/products")
@api(roles=())
def list_products(svc):
    return jsonify([product_json(p) for p in svc.list_products()])


@app.get("/api/products/<sku>")
@api(roles=())
def get_product(svc, sku):
    p = STATE.repo.get_product(sku)
    return jsonify(product=product_json(p), transactions=[tx_json(t) for t in svc.audit_trail(p.sku)])


@app.post("/api/products")
@api(mutates=True)
def create_product(svc):
    d = body()
    cat = (d.get("category") or "").lower()
    if cat not in ProductFactory.CATEGORIES:
        raise ValueError(f"Unsupported product category: {cat or '(none)'}")
    sku, name = (d.get("sku") or "").strip(), (d.get("name") or "").strip()
    if not sku or not name:
        raise ValueError("SKU and name are required")
    extra = {}
    if cat == "perishable" and d.get("expiry_date"):
        extra["expiry_date"] = d["expiry_date"]
    if cat == "electronic" and d.get("warranty_months") not in (None, ""):
        extra["warranty_months"] = num(d, "warranty_months", int)
    if cat == "bulk" and d.get("unit_measure"):
        extra["unit_measure"] = d["unit_measure"]
    p = svc.register_product(cat, sku, name, num(d, "unit_price", float),
                             num(d, "reorder_level", int), **extra)
    qty = num(d, "initial_qty", int, required=False)
    if qty:
        svc.receive_stock(p.sku, qty, num(d, "unit_cost", float, required=False))
    return jsonify(product_json(p)), 201


@app.post("/api/products/<sku>/receive")
@api(mutates=True)
def receive(svc, sku):
    d = body()
    p = svc.receive_stock(sku, num(d, "qty", int), num(d, "unit_cost", float, required=False))
    return jsonify(product=product_json(p))


@app.post("/api/products/<sku>/issue")
@api(mutates=True)
def issue(svc, sku):
    alerts = svc.issue_stock(sku, num(body(), "qty", int))
    return jsonify(product=product_json(STATE.repo.get_product(sku)), alerts=alerts)


@app.post("/api/products/<sku>/discontinue")
@api(mutates=True)
def discontinue(svc, sku):
    return jsonify(product=product_json(svc.discontinue_product(sku)))


@app.post("/api/valuation")
@api(roles=("manager",), mutates=True)
def set_valuation(svc):
    key = body().get("strategy")
    if key not in STRATEGIES:
        raise ValueError("strategy must be 'standard' or 'fifo'")
    STATE.strategy_key = key
    svc.set_valuation_strategy(STRATEGIES[key]())
    return jsonify(active=svc.valuation_strategy.name, total=svc.get_total_valuation())


@app.get("/api/valuation")
@api(roles=())
def get_valuation(svc):
    rows = []
    for p in svc.list_products():
        remaining, fifo = p.quantity, 0.0
        for b in STATE.repo.get_batches(p.sku):
            take = min(remaining, b.qty)
            fifo += take * b.unit_cost
            remaining -= take
        fifo += remaining * p.unit_price
        rows.append({"sku": p.sku, "name": p.name, "quantity": p.quantity,
                     "standard": round(p.quantity * p.unit_price, 2), "fifo": round(fifo, 2)})
    return jsonify(active=svc.valuation_strategy.name, active_key=STATE.strategy_key,
                   total=svc.get_total_valuation(), rows=rows,
                   standard=StandardCostValuation().valuate(STATE.repo),
                   fifo=FIFOValuation().valuate(STATE.repo))


@app.post("/api/sync")
@api(mutates=True)
def sync(svc):
    csv_text = (body().get("csv") or "").strip()
    legacy = LegacyCSVSupplierSystem(csv_text) if csv_text else LegacyCSVSupplierSystem()
    adapter = LegacyCSVSupplierAdapter(legacy)
    records = adapter.fetch_records()
    if not records:
        raise ValueError("No valid records found. Expected lines: sku,name,category,price,qty")
    log = svc.sync_supplier_feed(adapter)
    return jsonify(log=log, records=len(records))


@app.get("/api/transactions")
@api(roles=())
def transactions(svc):
    sku = request.args.get("sku") or None
    return jsonify([tx_json(t) for t in reversed(svc.audit_trail(sku))])


@app.get("/api/alerts")
@api(roles=())
def alerts(svc):
    return jsonify(
        purchase_orders=[{"po_id": po.po_id, "sku": po.sku, "qty": po.qty, "status": po.status}
                         for po in reversed(STATE.auto_po.purchase_orders)],
        emails=list(reversed(STATE.email.outbox)))


@app.post("/api/purchase-orders/<po_id>/<action>")
@api(roles=("manager",), mutates=True)
def po_action(svc, po_id, action):
    po = next((p for p in STATE.auto_po.purchase_orders if p.po_id == po_id), None)
    if po is None:
        raise KeyError(f"Unknown purchase order {po_id}")
    if po.status != "DRAFT":
        raise ValueError(f"{po_id} is already {po.status}")
    if action == "receive":
        svc.receive_stock(po.sku, po.qty, num(body(), "unit_cost", float, required=False))
        po.status = "RECEIVED"
    elif action == "cancel":
        po.status = "CANCELLED"
    else:
        raise ValueError("action must be 'receive' or 'cancel'")
    return jsonify(po_id=po.po_id, status=po.status)


@app.post("/api/reset")
@api(roles=("manager",))
def reset(svc):
    global STATE
    STATE = AppState()
    seed(STATE)
    save_state()
    return jsonify(ok=True)


if __name__ == "__main__":
    print(" * Inventory Management System running at http://127.0.0.1:5000")
    app.run(debug=False, port=5000)
