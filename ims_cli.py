"""
ims_cli.py - Presentation layer: interactive menu-driven Inventory Management System.

Run:  python ims_cli.py
Logins:  manager / manager123   (all operations)
         staff   / staff123     (receive / issue / view)
"""
from after_ims import (
    AuthService, AutoReorderObserver, EmailAlertObserver, FIFOValuation, InventoryRepository,
    InventoryService, LegacyCSVSupplierAdapter, LegacyCSVSupplierSystem, ProductFactory,
    StandardCostValuation,
)


def ask(prompt, cast=str, default=None):
    while True:
        raw = input(f"{prompt}{f' [{default}]' if default is not None else ''}: ").strip()
        if raw == "" and default is not None:
            return default
        try:
            return cast(raw)
        except ValueError:
            print("  Invalid value, try again.")


def print_products(products):
    if not products:
        print("  (no products)")
        return
    print(f"  {'SKU':<9}{'Name':<18}{'Category':<12}{'Qty':>6}{'Price':>9}{'Reorder':>9}  State / Details")
    print("  " + "-" * 92)
    for p in products:
        print(f"  {p.sku:<9}{p.name[:17]:<18}{p.category:<12}{p.quantity:>6}{p.unit_price:>9.2f}"
              f"{p.reorder_level:>9}  {p.state.value} / {p.details()}")


def main():
    auth = AuthService()
    svc = InventoryService(InventoryRepository(), StandardCostValuation(), auth)
    email, auto_po = EmailAlertObserver(), AutoReorderObserver()
    svc.attach(email)
    svc.attach(auto_po)

    print("=== Inventory Management System ===")
    while True:
        if auth.current_user is None:
            print("\nLogin (manager/manager123 or staff/staff123). Type 'q' as username to quit.")
            user = input("Username: ").strip()
            if user.lower() == "q":
                break
            if not auth.login(user, input("Password: ").strip()):
                print("  Invalid credentials.")
            continue

        print(f"\n[{auth.current_user} / {auth.current_role}]  Valuation: {svc.valuation_strategy.name}")
        print(" 1. Register product        2. Receive stock         3. Issue stock\n"
              " 4. List products           5. Low-stock report      6. Valuation report\n"
              " 7. Switch valuation        8. Sync supplier CSV     9. Audit trail\n"
              "10. Purchase orders & alerts 11. Discontinue product 12. Product handling policy\n"
              " 0. Logout")
        choice = input("Choice: ").strip()
        try:
            if choice == "1":
                cat = ask(f"Category {ProductFactory.CATEGORIES}").lower()
                if cat not in ProductFactory.CATEGORIES:
                    raise ValueError(f"Unsupported product category: {cat}")
                sku = ask("SKU")
                name = ask("Name")
                price = ask("Unit price", float)
                reorder = ask("Reorder level", int)
                extra = {}
                if cat == "perishable":
                    extra["expiry_date"] = ask("Expiry date (YYYY-MM-DD)", str, "2026-12-31")
                elif cat == "electronic":
                    extra["warranty_months"] = ask("Warranty months", int, 12)
                else:
                    extra["unit_measure"] = ask("Unit measure", str, "kg")
                p = svc.register_product(cat, sku, name, price, reorder, **extra)
                print(f"  Registered {type(p).__name__} {p.sku}. Policy: {p.get_handling_policy()}")
            elif choice == "2":
                sku = ask("SKU")
                qty = ask("Quantity", int)
                cost = ask("Unit cost (blank = list price)", str, "")
                p = svc.receive_stock(sku, qty, float(cost) if cost else None)
                print(f"  {p.sku} now has {p.quantity} units ({p.state.value}).")
            elif choice == "3":
                sku = ask("SKU")
                qty = ask("Quantity", int)
                alerts = svc.issue_stock(sku, qty)
                print(f"  Issued {qty} units of {sku}.")
                for a in alerts:
                    print("  " + a)
            elif choice == "4":
                print_products(svc.list_products())
            elif choice == "5":
                print_products(svc.low_stock_products())
            elif choice == "6":
                std = StandardCostValuation().valuate(svc._repo)
                fifo = FIFOValuation().valuate(svc._repo)
                print(f"  Active ({svc.valuation_strategy.name}): ${svc.get_total_valuation():,.2f}")
                print(f"  Standard Cost: ${std:,.2f}   FIFO Batch: ${fifo:,.2f}")
            elif choice == "7":
                auth.require("manager")
                new = FIFOValuation() if isinstance(svc.valuation_strategy, StandardCostValuation) \
                    else StandardCostValuation()
                svc.set_valuation_strategy(new)
                print(f"  Switched to {new.name}: ${svc.get_total_valuation():,.2f}")
            elif choice == "8":
                print("  Paste CSV lines 'sku,name,category,price,qty' (blank line to finish),")
                print("  or press Enter immediately to use the built-in legacy supplier feed.")
                lines = []
                while True:
                    l = input("  > ")
                    if not l.strip():
                        break
                    lines.append(l)
                legacy = LegacyCSVSupplierSystem("\n".join(lines)) if lines else LegacyCSVSupplierSystem()
                for msg in svc.sync_supplier_feed(LegacyCSVSupplierAdapter(legacy)) or ["  No valid records."]:
                    print("  " + msg)
            elif choice == "9":
                sku = ask("SKU filter (blank = all)", str, "")
                for tx in svc.audit_trail(sku or None) or ["(none)"]:
                    print("  ", tx)
            elif choice == "10":
                print("  Purchase orders:")
                for po in auto_po.purchase_orders or ["(none)"]:
                    print("   ", po)
                print("  Email alerts:")
                for m in email.outbox or ["(none)"]:
                    print("   ", m)
            elif choice == "11":
                p = svc.discontinue_product(ask("SKU"))
                print(f"  {p.sku} -> {p.state.value}")
            elif choice == "12":
                p = svc._repo.get_product(ask("SKU"))
                print(f"  {p.sku}: {p.get_handling_policy()}")
            elif choice == "0":
                auth.logout()
            else:
                print("  Unknown option.")
        except (ValueError, KeyError, PermissionError) as e:
            print(f"  Error: {e}")
        except Exception as e:  # InsufficientStockError etc.
            print(f"  Error: {e}")
    print("Goodbye.")


if __name__ == "__main__":
    main()
