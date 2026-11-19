"""
before_ims.py - Monolithic BASELINE Inventory Management System (anti-pattern reference).

Everything (product creation, stock math, CSV parsing, valuation, alerting) lives inside
a single InventoryManager "god class" operating on raw dictionaries and one giant
handle_operation() switchboard. Kept only to contrast against after_ims.py.
"""


class InventoryManager:
    def __init__(self):
        self.products = {}      # sku -> raw dict
        self.batches = {}       # sku -> list of [qty, cost]
        self.transactions = []  # list of raw dicts
        self.valuation_mode = "standard"
        self.legacy_csv = "SKU-301,Portland Cement,bulk,9.10,5\nSKU-401,Basmati Rice,bulk,1.85,20"

    def handle_operation(self, op, **kw):
        if op == "register":
            cat = kw["category"].lower()
            p = {"sku": kw["sku"], "name": kw["name"], "price": kw["price"],
                 "reorder": kw["reorder"], "qty": 0, "category": cat}
            if cat == "perishable":
                p["expiry"] = kw.get("expiry", "2026-12-31")
                p["policy"] = "Cold-chain storage, FEFO dispatch"
            elif cat == "electronic":
                p["warranty"] = kw.get("warranty", 12)
                p["policy"] = "ESD-safe shelving"
            elif cat == "bulk":
                p["unit"] = kw.get("unit", "kg")
                p["policy"] = "Pallet racking, moisture control"
            else:
                print("bad category")
                return
            self.products[kw["sku"]] = p
            self.batches[kw["sku"]] = []
            self.transactions.append({"type": "REGISTER", "sku": kw["sku"], "qty": 0})
        elif op == "receive":
            p = self.products.get(kw["sku"])
            if p is None:
                print("no such sku")
                return
            p["qty"] += kw["qty"]
            self.batches[kw["sku"]].append([kw["qty"], kw.get("cost", p["price"])])
            self.transactions.append({"type": "INBOUND", "sku": kw["sku"], "qty": kw["qty"]})
        elif op == "issue":
            p = self.products.get(kw["sku"])
            if p is None:
                print("no such sku")
                return
            if p["qty"] < kw["qty"]:
                print("insufficient stock")
                return
            p["qty"] -= kw["qty"]
            left = kw["qty"]
            for b in self.batches[kw["sku"]]:
                take = min(left, b[0])
                b[0] -= take
                left -= take
            self.transactions.append({"type": "OUTBOUND", "sku": kw["sku"], "qty": kw["qty"]})
            if p["qty"] <= p["reorder"]:
                # hardcoded alerting - cannot add new reactions without editing this
                print(f"EMAIL: low stock for {p['sku']} ({p['qty']} left)")
        elif op == "sync":
            for line in self.legacy_csv.splitlines():
                sku, name, cat, price, qty = line.split(",")
                if sku not in self.products:
                    self.handle_operation("register", sku=sku, name=name, category=cat,
                                          price=float(price), reorder=5)
                self.handle_operation("receive", sku=sku, qty=int(qty), cost=float(price))
        elif op == "valuate":
            total = 0.0
            if self.valuation_mode == "standard":
                for p in self.products.values():
                    total += p["qty"] * p["price"]
            elif self.valuation_mode == "fifo":
                for sku, p in self.products.items():
                    left = p["qty"]
                    for q, c in self.batches[sku]:
                        take = min(left, q)
                        total += take * c
                        left -= take
            return round(total, 2)


if __name__ == "__main__":
    m = InventoryManager()
    m.handle_operation("register", sku="SKU-101", name="Fresh Milk", category="perishable", price=2.5, reorder=15)
    m.handle_operation("receive", sku="SKU-101", qty=50, cost=2.5)
    m.handle_operation("issue", sku="SKU-101", qty=38)
    print("Standard valuation:", m.handle_operation("valuate"))
