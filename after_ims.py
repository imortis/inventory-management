"""
after_ims.py - Refactored Object-Oriented Inventory Management System.

Layered architecture:
  Presentation  -> ims_cli.py (interactive CLI) / test_and_demo_ims.py
  Service       -> InventoryService, AuthService
  Domain        -> Product hierarchy, ProductFactory, StockTransaction,
                   StockObserver, ValuationStrategy (patterns)
  Data/Integr.  -> InventoryRepository, ISupplierFeed, LegacyCSVSupplierAdapter

Design patterns: Factory Method (ProductFactory), Adapter (LegacyCSVSupplierAdapter),
Observer (StockObserver), Strategy (ValuationStrategy).
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


# ============================== DOMAIN LAYER ==============================

class ProductState(Enum):
    """States from the Product stock-lifecycle statechart (Figure 6)."""
    OUT_OF_STOCK = "Out of Stock"
    IN_STOCK = "In Stock"
    LOW_STOCK = "Low Stock"
    REORDER_PENDING = "Reorder Pending"
    DISCONTINUED = "Discontinued"


class InsufficientStockError(Exception):
    pass


class Product(ABC):
    """Abstract base class - encapsulates stock invariants."""

    def __init__(self, sku: str, name: str, unit_price: float, reorder_level: int, quantity: int = 0):
        if not sku or not sku.strip():
            raise ValueError("SKU must not be empty")
        if unit_price < 0:
            raise ValueError("Unit price must be non-negative")
        if reorder_level < 0 or quantity < 0:
            raise ValueError("Reorder level and quantity must be non-negative")
        self._sku = sku.strip()
        self._name = name
        self._unit_price = float(unit_price)
        self._reorder_level = int(reorder_level)
        self._quantity = int(quantity)
        self._reorder_pending = False
        self._discontinued = False

    # --- read-only accessors (information hiding) ---
    @property
    def sku(self) -> str: return self._sku
    @property
    def name(self) -> str: return self._name
    @property
    def unit_price(self) -> float: return self._unit_price
    @property
    def reorder_level(self) -> int: return self._reorder_level
    @property
    def quantity(self) -> int: return self._quantity

    @property
    def category(self) -> str:
        return type(self).__name__.replace("Item", "").lower()

    # --- behaviour ---
    def add_stock(self, qty: int) -> None:
        if self._discontinued:
            raise ValueError(f"{self._sku} is discontinued")
        if qty <= 0:
            raise ValueError("Quantity to add must be positive")
        self._quantity += qty
        if not self.needs_reorder():
            self._reorder_pending = False

    def remove_stock(self, qty: int) -> None:
        if qty <= 0:
            raise ValueError("Quantity to remove must be positive")
        if qty > self._quantity:
            raise InsufficientStockError(
                f"Insufficient stock for {self._sku}: requested {qty}, available {self._quantity}")
        self._quantity -= qty

    def needs_reorder(self) -> bool:
        return self._quantity <= self._reorder_level

    def mark_reorder_pending(self) -> None:
        self._reorder_pending = True

    def discontinue(self) -> None:
        self._discontinued = True

    @property
    def state(self) -> ProductState:
        if self._discontinued:
            return ProductState.DISCONTINUED
        if self._quantity == 0 and not self._reorder_pending:
            return ProductState.OUT_OF_STOCK
        if self.needs_reorder():
            return ProductState.REORDER_PENDING if self._reorder_pending else ProductState.LOW_STOCK
        return ProductState.IN_STOCK

    @abstractmethod
    def get_handling_policy(self) -> str: ...

    @abstractmethod
    def details(self) -> str: ...

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(sku={self._sku}, name={self._name}, qty={self._quantity}, "
                f"price={self._unit_price:.2f}, reorder={self._reorder_level})")


class PerishableItem(Product):
    def __init__(self, sku, name, unit_price, reorder_level, quantity=0, expiry_date="2026-12-31"):
        super().__init__(sku, name, unit_price, reorder_level, quantity)
        self._expiry_date = expiry_date

    @property
    def expiry_date(self) -> str: return self._expiry_date

    def get_handling_policy(self) -> str:
        return f"Cold-chain storage (2-8C), FEFO dispatch, expires {self._expiry_date}"

    def details(self) -> str:
        return f"expiry={self._expiry_date}"


class ElectronicItem(Product):
    def __init__(self, sku, name, unit_price, reorder_level, quantity=0, warranty_months=12):
        super().__init__(sku, name, unit_price, reorder_level, quantity)
        self._warranty_months = int(warranty_months)

    @property
    def warranty_months(self) -> int: return self._warranty_months

    def get_handling_policy(self) -> str:
        return f"ESD-safe shelving, serial tracking, {self._warranty_months}-month warranty"

    def details(self) -> str:
        return f"warranty={self._warranty_months}m"


class BulkItem(Product):
    def __init__(self, sku, name, unit_price, reorder_level, quantity=0, unit_measure="kg"):
        super().__init__(sku, name, unit_price, reorder_level, quantity)
        self._unit_measure = unit_measure

    @property
    def unit_measure(self) -> str: return self._unit_measure

    def get_handling_policy(self) -> str:
        return f"Pallet racking, moisture control, measured in {self._unit_measure}"

    def details(self) -> str:
        return f"unit={self._unit_measure}"


class ProductFactory:
    """Factory Method - isolates concrete subclass instantiation."""

    CATEGORIES = ("perishable", "electronic", "bulk")

    @staticmethod
    def create_product(category: str, sku: str, name: str, unit_price: float,
                       reorder_level: int, quantity: int = 0, **extra) -> Product:
        cat = category.strip().lower()
        if cat == "perishable":
            return PerishableItem(sku, name, unit_price, reorder_level, quantity,
                                  extra.get("expiry_date", "2026-12-31"))
        if cat == "electronic":
            return ElectronicItem(sku, name, unit_price, reorder_level, quantity,
                                  int(extra.get("warranty_months", 12)))
        if cat == "bulk":
            return BulkItem(sku, name, unit_price, reorder_level, quantity,
                            extra.get("unit_measure", "kg"))
        raise ValueError(f"Unsupported product category: {category}")


class TxType(Enum):
    REGISTER = "REGISTER"
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    SYNC = "SYNC"
    DISCONTINUE = "DISCONTINUE"


@dataclass(frozen=True)
class StockTransaction:
    """Immutable audit record."""
    tx_id: int
    tx_type: TxType
    sku: str
    qty: int
    unit_cost: float
    user: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def __str__(self) -> str:
        return (f"#{self.tx_id:03d} [{self.timestamp}] {self.tx_type.value:<11} {self.sku:<8} "
                f"qty={self.qty:<5} cost={self.unit_cost:>8.2f} by {self.user}")


@dataclass
class Batch:
    qty: int
    unit_cost: float


@dataclass(frozen=True)
class SupplierRecord:
    sku: str
    name: str
    category: str
    unit_price: float
    quantity: int


# ---------------- Observer ----------------
class StockObserver(ABC):
    @abstractmethod
    def on_low_stock(self, product: Product) -> str: ...


class EmailAlertObserver(StockObserver):
    def __init__(self, recipient: str = "inventory.manager@warehouse.local"):
        self.recipient = recipient
        self.outbox: List[str] = []

    def on_low_stock(self, product: Product) -> str:
        msg = (f"[EMAIL -> {self.recipient}] LOW STOCK: {product.sku} '{product.name}' has "
               f"{product.quantity} units (reorder level {product.reorder_level}).")
        self.outbox.append(msg)
        return msg


@dataclass
class PurchaseOrder:
    po_id: str
    sku: str
    qty: int
    status: str = "DRAFT"


class AutoReorderObserver(StockObserver):
    def __init__(self, target_multiplier: int = 3):
        self.target_multiplier = target_multiplier
        self.purchase_orders: List[PurchaseOrder] = []

    def on_low_stock(self, product: Product) -> str:
        qty = max(product.reorder_level * self.target_multiplier - product.quantity, 1)
        po = PurchaseOrder(f"PO-{len(self.purchase_orders) + 1:04d}", product.sku, qty)
        self.purchase_orders.append(po)
        product.mark_reorder_pending()
        return f"[AUTO-PO] Drafted {po.po_id} for {qty} units of {product.sku}."


# ---------------- Strategy ----------------
class ValuationStrategy(ABC):
    name = "abstract"

    @abstractmethod
    def valuate(self, repo: "InventoryRepository") -> float: ...


class StandardCostValuation(ValuationStrategy):
    name = "Standard Cost"

    def valuate(self, repo: "InventoryRepository") -> float:
        return round(sum(p.quantity * p.unit_price for p in repo.all_products()), 2)


class FIFOValuation(ValuationStrategy):
    name = "FIFO Batch"

    def valuate(self, repo: "InventoryRepository") -> float:
        total = 0.0
        for p in repo.all_products():
            remaining = p.quantity
            for b in repo.get_batches(p.sku):
                if remaining <= 0:
                    break
                take = min(remaining, b.qty)
                total += take * b.unit_cost
                remaining -= take
            total += remaining * p.unit_price  # stock without batch history
        return round(total, 2)


# ======================= DATA ACCESS & INTEGRATION ========================

class InventoryRepository:
    """In-memory store. Aggregates Products, composes StockTransactions."""

    def __init__(self):
        self._products: Dict[str, Product] = {}
        self._batches: Dict[str, List[Batch]] = {}
        self._transactions: List[StockTransaction] = []

    def save_product(self, p: Product) -> None:
        self._products[p.sku] = p
        self._batches.setdefault(p.sku, [])

    def get_product(self, sku: str) -> Product:
        try:
            return self._products[sku.strip()]
        except KeyError:
            raise KeyError(f"Unknown SKU: {sku}") from None

    def exists(self, sku: str) -> bool:
        return sku.strip() in self._products

    def all_products(self) -> List[Product]:
        return list(self._products.values())

    def add_batch(self, sku: str, qty: int, unit_cost: float) -> None:
        self._batches[sku].append(Batch(qty, unit_cost))

    def consume_batches(self, sku: str, qty: int) -> None:
        """Remove issued quantity from oldest batches first (FIFO)."""
        remaining = qty
        batches = self._batches[sku]
        while remaining > 0 and batches:
            take = min(remaining, batches[0].qty)
            batches[0].qty -= take
            remaining -= take
            if batches[0].qty == 0:
                batches.pop(0)

    def get_batches(self, sku: str) -> List[Batch]:
        return list(self._batches.get(sku, []))

    def log_transaction(self, tx_type: TxType, sku: str, qty: int, unit_cost: float, user: str) -> StockTransaction:
        tx = StockTransaction(len(self._transactions) + 1, tx_type, sku, qty, unit_cost, user)
        self._transactions.append(tx)
        return tx

    def get_transactions(self, sku: Optional[str] = None) -> List[StockTransaction]:
        if sku:
            return [t for t in self._transactions if t.sku == sku]
        return list(self._transactions)


class ISupplierFeed(ABC):
    @abstractmethod
    def fetch_records(self) -> List[SupplierRecord]: ...


class LegacyCSVSupplierSystem:
    """Third-party legacy system - cannot be modified."""

    def __init__(self, csv_dump: Optional[str] = None):
        self._dump = csv_dump if csv_dump is not None else (
            "sku,name,category,price,qty\n"
            "SKU-301,Portland Cement,bulk,9.10,5\n"
            "SKU-401,Basmati Rice,bulk,1.85,20\n")

    def get_csv_dump(self) -> str:
        return self._dump


class LegacyCSVSupplierAdapter(ISupplierFeed):
    """Adapter - converts raw CSV lines into SupplierRecord objects."""

    def __init__(self, legacy: LegacyCSVSupplierSystem):
        self._legacy = legacy

    def fetch_records(self) -> List[SupplierRecord]:
        records = []
        for line in self._legacy.get_csv_dump().strip().splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) != 5 or parts[0].lower() == "sku":
                continue  # header / malformed
            try:
                records.append(SupplierRecord(parts[0], parts[1], parts[2].lower(),
                                              float(parts[3]), int(parts[4])))
            except ValueError:
                continue
        return records


# ============================== SERVICE LAYER ==============================

class AuthService:
    """<<include>> Authenticate User."""

    ROLES = ("manager", "staff")

    def __init__(self):
        self._users: Dict[str, tuple] = {}
        self.current_user: Optional[str] = None
        self.current_role: Optional[str] = None
        self.add_user("manager", "manager123", "manager")
        self.add_user("staff", "staff123", "staff")

    @staticmethod
    def _hash(pw: str) -> str:
        return hashlib.sha256(pw.encode()).hexdigest()

    def add_user(self, username: str, password: str, role: str) -> None:
        if role not in self.ROLES:
            raise ValueError("Invalid role")
        self._users[username] = (self._hash(password), role)

    def login(self, username: str, password: str) -> bool:
        rec = self._users.get(username)
        if rec and rec[0] == self._hash(password):
            self.current_user, self.current_role = username, rec[1]
            return True
        return False

    def logout(self) -> None:
        self.current_user = self.current_role = None

    def require(self, *roles: str) -> str:
        if self.current_user is None:
            raise PermissionError("Not authenticated")
        if roles and self.current_role not in roles:
            raise PermissionError(f"Role '{self.current_role}' not permitted for this action")
        return self.current_user


class InventoryService:
    """Application service orchestrating all use cases (UC1-UC6)."""

    def __init__(self, repo: InventoryRepository, valuation: Optional[ValuationStrategy] = None,
                 auth: Optional[AuthService] = None):
        self._repo = repo
        self._valuation_strategy = valuation or StandardCostValuation()
        self._observers: List[StockObserver] = []
        self._auth = auth

    def _user(self, *roles: str) -> str:
        return self._auth.require(*roles) if self._auth else "system"

    # --- Observer management ---
    def attach(self, obs: StockObserver) -> None:
        if obs not in self._observers:
            self._observers.append(obs)

    def detach(self, obs: StockObserver) -> None:
        self._observers.remove(obs)

    def _notify(self, product: Product) -> List[str]:
        return [o.on_low_stock(product) for o in self._observers]

    # --- UC1 ---
    def register_product(self, category: str, sku: str, name: str, unit_price: float,
                         reorder_level: int, **extra) -> Product:
        user = self._user("manager")
        if self._repo.exists(sku):
            raise ValueError(f"SKU {sku} already exists")
        product = ProductFactory.create_product(category, sku, name, unit_price, reorder_level, 0, **extra)
        self._repo.save_product(product)
        self._repo.log_transaction(TxType.REGISTER, product.sku, 0, product.unit_price, user)
        return product

    # --- UC2 ---
    def receive_stock(self, sku: str, qty: int, unit_cost: Optional[float] = None) -> Product:
        user = self._user("manager", "staff")
        product = self._repo.get_product(sku)
        cost = product.unit_price if unit_cost is None else float(unit_cost)
        if cost < 0:
            raise ValueError("Unit cost must be non-negative")
        product.add_stock(qty)
        self._repo.add_batch(product.sku, qty, cost)
        self._repo.log_transaction(TxType.INBOUND, product.sku, qty, cost, user)
        return product

    # --- UC3 (+ UC4 <<extend>>) ---
    def issue_stock(self, sku: str, qty: int) -> List[str]:
        user = self._user("manager", "staff")
        product = self._repo.get_product(sku)
        product.remove_stock(qty)
        self._repo.consume_batches(product.sku, qty)
        self._repo.log_transaction(TxType.OUTBOUND, product.sku, qty, product.unit_price, user)
        if product.needs_reorder():
            return self._notify(product)
        return []

    # --- UC5 ---
    def set_valuation_strategy(self, strategy: ValuationStrategy) -> None:
        self._valuation_strategy = strategy

    @property
    def valuation_strategy(self) -> ValuationStrategy:
        return self._valuation_strategy

    def get_total_valuation(self) -> float:
        return self._valuation_strategy.valuate(self._repo)

    # --- UC6 ---
    def sync_supplier_feed(self, feed: ISupplierFeed, default_reorder: int = 5) -> List[str]:
        user = self._user("manager")
        log = []
        for rec in feed.fetch_records():
            if self._repo.exists(rec.sku):
                product = self._repo.get_product(rec.sku)
                log.append(f"Updated existing {rec.sku}: +{rec.quantity}")
            else:
                product = ProductFactory.create_product(rec.category, rec.sku, rec.name,
                                                        rec.unit_price, default_reorder)
                self._repo.save_product(product)
                self._repo.log_transaction(TxType.REGISTER, rec.sku, 0, rec.unit_price, user)
                log.append(f"Registered new {rec.sku} ({rec.category}): +{rec.quantity}")
            if rec.quantity > 0:
                product.add_stock(rec.quantity)
                self._repo.add_batch(rec.sku, rec.quantity, rec.unit_price)
                self._repo.log_transaction(TxType.SYNC, rec.sku, rec.quantity, rec.unit_price, user)
        return log

    # --- misc ---
    def discontinue_product(self, sku: str) -> Product:
        user = self._user("manager")
        product = self._repo.get_product(sku)
        product.discontinue()
        self._repo.log_transaction(TxType.DISCONTINUE, product.sku, 0, product.unit_price, user)
        return product

    def list_products(self) -> List[Product]:
        return self._repo.all_products()

    def low_stock_products(self) -> List[Product]:
        return [p for p in self._repo.all_products() if p.needs_reorder() and
                p.state != ProductState.DISCONTINUED]

    def audit_trail(self, sku: Optional[str] = None) -> List[StockTransaction]:
        return self._repo.get_transactions(sku)
