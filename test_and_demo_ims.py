"""
test_and_demo_ims.py - 5 unit tests + UC1-UC6 demonstration for after_ims.py.

Run:  python test_and_demo_ims.py
"""
import unittest

from after_ims import (
    AuthService, AutoReorderObserver, BulkItem, ElectronicItem, EmailAlertObserver,
    FIFOValuation, InsufficientStockError, InventoryRepository, InventoryService,
    LegacyCSVSupplierAdapter, LegacyCSVSupplierSystem, PerishableItem, ProductFactory,
    ProductState, StandardCostValuation,
)


def build_demo_service():
    """Seed data reproducing the scenario from the report (Figures 12-15)."""
    auth = AuthService()
    auth.login("manager", "manager123")
    svc = InventoryService(InventoryRepository(), StandardCostValuation(), auth)
    email, auto_po = EmailAlertObserver(), AutoReorderObserver()
    svc.attach(email)
    svc.attach(auto_po)
    return svc, email, auto_po


class TestIMS(unittest.TestCase):
    def setUp(self):
        self.svc = InventoryService(InventoryRepository())

    def test_1_factory_method(self):
        self.assertIsInstance(ProductFactory.create_product("perishable", "P1", "Milk", 2.5, 10), PerishableItem)
        self.assertIsInstance(ProductFactory.create_product("Electronic", "E1", "Scanner", 45, 5), ElectronicItem)
        self.assertIsInstance(ProductFactory.create_product("bulk", "B1", "Cement", 9.1, 20), BulkItem)
        with self.assertRaises(ValueError):
            ProductFactory.create_product("toys", "T1", "Ball", 1, 1)

    def test_2_encapsulation_and_negative_stock(self):
        p = self.svc.register_product("bulk", "B1", "Cement", 9.1, 5)
        self.svc.receive_stock("B1", 10)
        with self.assertRaises(InsufficientStockError):
            self.svc.issue_stock("B1", 11)
        self.assertEqual(p.quantity, 10)
        with self.assertRaises(AttributeError):
            p.quantity = 999  # read-only property
        # access control: <<include>> Authenticate User
        auth = AuthService()
        secured = InventoryService(InventoryRepository(), auth=auth)
        with self.assertRaises(PermissionError):
            secured.register_product("bulk", "B2", "Sand", 1, 1)
        auth.login("staff", "staff123")
        with self.assertRaises(PermissionError):  # staff cannot register
            secured.register_product("bulk", "B2", "Sand", 1, 1)
        self.assertFalse(auth.login("staff", "wrong"))

    def test_3_observer_low_stock(self):
        email, po = EmailAlertObserver(), AutoReorderObserver()
        self.svc.attach(email)
        self.svc.attach(po)
        p = self.svc.register_product("perishable", "SKU-101", "Fresh Milk", 2.5, 15)
        self.svc.receive_stock("SKU-101", 50)
        self.assertEqual(self.svc.issue_stock("SKU-101", 10), [])
        msgs = self.svc.issue_stock("SKU-101", 28)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(len(email.outbox), 1)
        self.assertEqual(po.purchase_orders[0].sku, "SKU-101")
        self.assertEqual(p.state, ProductState.REORDER_PENDING)

    def test_4_adapter_supplier_feed(self):
        legacy = LegacyCSVSupplierSystem("sku,name,category,price,qty\nX1,Rice,bulk,1.85,20\nbad line\n"
                                         "X2,Router,electronic,30,4\n")
        recs = LegacyCSVSupplierAdapter(legacy).fetch_records()
        self.assertEqual([r.sku for r in recs], ["X1", "X2"])
        self.svc.sync_supplier_feed(LegacyCSVSupplierAdapter(legacy))
        self.assertEqual(self.svc.list_products()[0].quantity, 20)

    def test_5_strategy_valuation(self):
        self.svc.register_product("bulk", "B1", "Cement", 10.0, 1)
        self.svc.receive_stock("B1", 5, 8.0)
        self.svc.receive_stock("B1", 5, 12.0)
        self.svc.issue_stock("B1", 5)  # consumes the 8.0 batch
        self.assertEqual(self.svc.get_total_valuation(), 50.0)
        self.svc.set_valuation_strategy(FIFOValuation())
        self.assertEqual(self.svc.get_total_valuation(), 60.0)


def run_demo():
    line = "=" * 72
    svc, email, auto_po = build_demo_service()

    print(f"\n{line}\nUC1: Register Products via Factory Method\n{line}")
    for args, extra in [
        (("perishable", "SKU-101", "Fresh Milk", 2.50, 15), {"expiry_date": "2026-12-05"}),
        (("electronic", "SKU-201", "Barcode Scanner", 45.00, 5), {"warranty_months": 24}),
        (("bulk", "SKU-301", "Portland Cement", 9.10, 8), {"unit_measure": "bag"}),
    ]:
        p = svc.register_product(*args, **extra)
        print(f"  {type(p).__name__:<15} {p.sku}  {p.name:<16} -> {p.get_handling_policy()}")

    print(f"\n{line}\nUC2: Receive Stock (batch cost tracking)\n{line}")
    for sku, qty, cost in [("SKU-101", 30, 2.40), ("SKU-101", 20, 2.60),
                           ("SKU-201", 10, 45.30), ("SKU-301", 10, 9.28)]:
        p = svc.receive_stock(sku, qty, cost)
        print(f"  Received {qty:>3} x {sku} @ ${cost:.2f} -> on hand {p.quantity}")

    print(f"\n{line}\nUC6: Sync Supplier Feed via LegacyCSVSupplierAdapter\n{line}")
    for msg in svc.sync_supplier_feed(LegacyCSVSupplierAdapter(LegacyCSVSupplierSystem())):
        print("  " + msg)

    print(f"\n{line}\nUC3 + UC4: Issue Stock & Observer Alerts\n{line}")
    print("  Issuing 38 units of SKU-101 ...")
    for msg in svc.issue_stock("SKU-101", 38):
        print("  " + msg)
    milk = svc.list_products()[0]
    print(f"  SKU-101 now {milk.quantity} units (reorder level {milk.reorder_level}) -> state: {milk.state.value}")
    try:
        svc.issue_stock("SKU-201", 999)
    except Exception as e:
        print(f"  Blocked: {e}")

    print(f"\n{line}\nUC5: Valuation Strategy Switch & Audit Trail\n{line}")
    print(f"  {svc.valuation_strategy.name:<14} valuation: ${svc.get_total_valuation():,.2f}")
    svc.set_valuation_strategy(FIFOValuation())
    print(f"  {svc.valuation_strategy.name:<14} valuation: ${svc.get_total_valuation():,.2f}")
    print("  Audit trail:")
    for tx in svc.audit_trail():
        print("   ", tx)


if __name__ == "__main__":
    print("Running unit tests ...")
    result = unittest.main(exit=False, verbosity=2).result
    run_demo()
    ok = result.testsRun - len(result.failures) - len(result.errors)
    print(f"\nSummary: {ok}/{result.testsRun} unit tests passed; UC1-UC6 demo completed.")
