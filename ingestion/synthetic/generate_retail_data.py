import argparse
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 42
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "data" / "raw" / "synthetic"

# (county, price_factor): one store per entry; Nairobi has three stores
STORE_PLAN = [
    ("Nairobi", 1.10), ("Nairobi", 1.12), ("Nairobi", 1.08),
    ("Mombasa", 1.08), ("Kisumu", 1.00), ("Nakuru", 0.97),
    ("Uasin Gishu", 0.95), ("Nyeri", 0.96), ("Machakos", 1.02),
    ("Kisii", 0.98), ("Meru", 0.94), ("Kakamega", 0.99),
]

SUPPLIERS = [
    {"supplier_id": "SUP1", "supplier_name": "Rift Valley Grains Ltd", "county": "Nakuru"},
    {"supplier_id": "SUP2", "supplier_name": "Coast Staples Distributors", "county": "Mombasa"},
    {"supplier_id": "SUP3", "supplier_name": "Lake Region Produce Co", "county": "Kisumu"},
    {"supplier_id": "SUP4", "supplier_name": "Highland Dairy Suppliers", "county": "Nyeri"},
    {"supplier_id": "SUP5", "supplier_name": "Capital Foods Wholesale", "county": "Nairobi"},
    {"supplier_id": "SUP6", "supplier_name": "Savannah Oils Ltd", "county": "Machakos"},
]

# (name, category, unit, base_price_kes, kamis_commodity, supplier_id)
PRODUCT_CATALOG = [
    ("Maize flour 2kg", "Cereals", "pack", 150, "Maize flour", "SUP1"),
    ("Rice 2kg", "Cereals", "pack", 380, "Rice", "SUP2"),
    ("Wheat flour 2kg", "Cereals", "pack", 200, "Wheat flour", "SUP1"),
    ("Sugar 1kg", "Staples", "pack", 190, "Sugar", "SUP5"),
    ("Cooking oil 1L", "Staples", "bottle", 330, "Cooking oil", "SUP6"),
    ("Beans 1kg", "Pulses", "kg", 190, "Beans", "SUP3"),
    ("Tomatoes 1kg", "Vegetables", "kg", 110, "Tomatoes", "SUP3"),
    ("Onions 1kg", "Vegetables", "kg", 120, "Onions", "SUP3"),
    ("Irish potatoes 1kg", "Vegetables", "kg", 80, "Irish potato", "SUP3"),
    ("Cabbage 1kg", "Vegetables", "kg", 60, "Cabbage", "SUP3"),
    ("Kale bunch", "Vegetables", "bunch", 30, "Kale", "SUP3"),
    ("Milk 500ml", "Dairy", "pack", 65, "Milk", "SUP4"),
]

STORE_FIELDS = ["store_id", "store_name", "county", "opened_date"]
SUPPLIER_FIELDS = ["supplier_id", "supplier_name", "county"]
PRODUCT_FIELDS = ["product_id", "product_name", "category", "unit",
                  "base_price", "kamis_commodity", "supplier_id"]
SALE_FIELDS = ["transaction_id", "line_no", "store_id", "product_id",
               "quantity", "unit_price", "line_total", "payment_method", "sold_at"]
MOVE_FIELDS = ["movement_id", "store_id", "product_id", "movement_type",
               "quantity_change", "supplier_id", "moved_at"]


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def build_dimensions():
    products = []
    for i, (name, category, unit, base, kamis, sup) in enumerate(PRODUCT_CATALOG, start=1):
        products.append({
            "product_id": f"P{i:03d}", "product_name": name, "category": category,
            "unit": unit, "base_price": base, "kamis_commodity": kamis,
            "supplier_id": sup,
        })
    stores = []
    for i, (county, factor) in enumerate(STORE_PLAN, start=1):
        stores.append({
            "store_id": f"S{i:02d}", "store_name": f"Duka Kuu {county} {i:02d}",
            "county": county,
            "opened_date": date(2018 + i % 6, 1 + i % 12, 15).isoformat(),
            "price_factor": factor,
        })
    dim_dir = OUT_DIR / "dimensions"
    write_csv(dim_dir / "stores.csv", STORE_FIELDS, stores)
    write_csv(dim_dir / "suppliers.csv", SUPPLIER_FIELDS, SUPPLIERS)
    write_csv(dim_dir / "products.csv", PRODUCT_FIELDS, products)
    return stores, products


def generate_day(day, stores, products):
    rng = random.Random(f"{SEED}-{day.isoformat()}")
    drift = 1 + 0.0003 * (day - date(2026, 1, 1)).days
    traffic = 1.0
    if day.weekday() >= 5:
        traffic *= 1.3
    if day.day >= 25:
        traffic *= 1.2

    midnight = datetime.combine(day, datetime.min.time())
    sales_rows = []
    move_rows = []
    move_n = 0

    for store in stores:
        sid = store["store_id"]
        n_tx = int(rng.randint(80, 160) * traffic)
        for t in range(1, n_tx + 1):
            tx_id = f"{sid}-{day:%Y%m%d}-{t:04d}"
            sold_at = midnight + timedelta(seconds=rng.randint(7 * 3600, 21 * 3600 - 1))
            payment = rng.choices(["MPESA", "CASH", "CARD"], weights=[60, 30, 10])[0]
            basket = rng.sample(products, rng.randint(1, 6))
            for line_no, product in enumerate(basket, start=1):
                qty = rng.randint(1, 4)
                price = round(product["base_price"] * store["price_factor"]
                              * drift * (1 + rng.uniform(-0.04, 0.04)), 2)
                sales_rows.append({
                    "transaction_id": tx_id, "line_no": line_no, "store_id": sid,
                    "product_id": product["product_id"], "quantity": qty,
                    "unit_price": price, "line_total": round(price * qty, 2),
                    "payment_method": payment, "sold_at": sold_at.isoformat(),
                })
                move_n += 1
                move_rows.append({
                    "movement_id": f"{sid}-{day:%Y%m%d}-M{move_n:05d}",
                    "store_id": sid, "product_id": product["product_id"],
                    "movement_type": "SALE", "quantity_change": -qty,
                    "supplier_id": "", "moved_at": sold_at.isoformat(),
                })

        for product in products:
            if rng.random() < 0.25:
                move_n += 1
                move_rows.append({
                    "movement_id": f"{sid}-{day:%Y%m%d}-M{move_n:05d}",
                    "store_id": sid, "product_id": product["product_id"],
                    "movement_type": "RESTOCK", "quantity_change": rng.randint(20, 80),
                    "supplier_id": product["supplier_id"],
                    "moved_at": (midnight + timedelta(hours=6)).isoformat(),
                })
            if product["category"] in ("Vegetables", "Dairy") and rng.random() < 0.15:
                move_n += 1
                move_rows.append({
                    "movement_id": f"{sid}-{day:%Y%m%d}-M{move_n:05d}",
                    "store_id": sid, "product_id": product["product_id"],
                    "movement_type": "WASTAGE", "quantity_change": -rng.randint(1, 5),
                    "supplier_id": "",
                    "moved_at": (midnight + timedelta(hours=20)).isoformat(),
                })

    part = f"date={day.isoformat()}"
    n_sales = write_csv(OUT_DIR / "pos_transactions" / part / "part-0000.csv",
                        SALE_FIELDS, sales_rows)
    n_moves = write_csv(OUT_DIR / "inventory_movements" / part / "part-0000.csv",
                        MOVE_FIELDS, move_rows)
    return n_sales, n_moves


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic retail data")
    parser.add_argument("--start", default="2026-08-01")
    parser.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    stores, products = build_dimensions()
    total_sales = total_moves = 0
    day = start
    while day <= end:
        n_sales, n_moves = generate_day(day, stores, products)
        total_sales += n_sales
        total_moves += n_moves
        day += timedelta(days=1)

    print(f"Days: {(end - start).days + 1}")
    print(f"Sale lines written: {total_sales}")
    print(f"Inventory movements written: {total_moves}")
    print(f"Output folder: {OUT_DIR}")


if __name__ == "__main__":
    main()
