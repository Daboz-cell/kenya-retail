import argparse
import random
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion" / "synthetic"))

import generate_retail_data as gen
from common import BOOTSTRAP, TOPIC_INVENTORY, TOPIC_SALES, encode

STORES = [{"store_id": f"S{i:02d}", "factor": factor}
          for i, (county, factor) in enumerate(gen.STORE_PLAN, start=1)]
PRODUCTS = [{"product_id": f"P{i:03d}", "category": category, "base_price": base,
             "supplier_id": supplier}
            for i, (name, category, unit, base, kamis, supplier)
            in enumerate(gen.PRODUCT_CATALOG, start=1)]


def iso(moment):
    return moment.isoformat(timespec="seconds")


def build_movement(store_id, product_id, movement_type, change, supplier_id, now, movement_id):
    return {"event_id": uuid.uuid4().hex, "movement_id": movement_id,
            "store_id": store_id, "product_id": product_id,
            "movement_type": movement_type, "quantity_change": change,
            "supplier_id": supplier_id, "moved_at": iso(now)}


def build_sale(rng, now):
    """One receipt: returns (sale_event, list_of_inventory_events)."""
    store = rng.choice(STORES)
    drift = 1 + 0.0003 * (now.date() - date(2026, 1, 1)).days
    transaction_id = f"{store['store_id']}-{now:%Y%m%d}-{uuid.uuid4().hex[:8]}"
    lines, movements = [], []
    for line_no, product in enumerate(rng.sample(PRODUCTS, rng.randint(1, 6)), start=1):
        quantity = rng.randint(1, 4)
        price = round(product["base_price"] * store["factor"] * drift
                      * (1 + rng.uniform(-0.04, 0.04)), 2)
        lines.append({"line_no": line_no, "product_id": product["product_id"],
                      "quantity": quantity, "unit_price": price,
                      "line_total": round(price * quantity, 2)})
        movements.append(build_movement(store["store_id"], product["product_id"], "SALE",
                                        -quantity, "", now, f"{transaction_id}-L{line_no}"))
    sale = {"event_id": uuid.uuid4().hex, "transaction_id": transaction_id,
            "store_id": store["store_id"], "sold_at": iso(now),
            "payment_method": rng.choices(["MPESA", "CASH", "CARD"], weights=[60, 30, 10])[0],
            "lines": lines}
    return sale, movements


def build_stock_event(rng, now):
    """A restock (stock arrives) or a wastage (perishable goods thrown away)."""
    store = rng.choice(STORES)
    if rng.random() < 0.7:
        product = rng.choice(PRODUCTS)
        return build_movement(store["store_id"], product["product_id"], "RESTOCK",
                              rng.randint(20, 80), product["supplier_id"], now,
                              f"{store['store_id']}-{now:%Y%m%d}-R{uuid.uuid4().hex[:6]}")
    product = rng.choice([p for p in PRODUCTS if p["category"] in ("Vegetables", "Dairy")])
    return build_movement(store["store_id"], product["product_id"], "WASTAGE",
                          -rng.randint(1, 5), "", now,
                          f"{store['store_id']}-{now:%Y%m%d}-W{uuid.uuid4().hex[:6]}")


def make_bad_sale(rng, now):
    """A deliberately broken sales message, to prove the dead letter path."""
    sale, _ = build_sale(rng, now)
    kind = rng.choice(["bad_json", "missing_store", "negative_quantity"])
    if kind == "bad_json":
        return b'{"event_id": "broken", "store_id": '
    if kind == "missing_store":
        del sale["store_id"]
    else:
        sale["lines"][0]["quantity"] = -2
    return sale


def main():
    parser = argparse.ArgumentParser(description="Simulate live POS and inventory events")
    parser.add_argument("--events", type=int, default=100,
                        help="number of receipts to send (0 = run until Ctrl+C)")
    parser.add_argument("--rate", type=float, default=5.0, help="receipts per second")
    parser.add_argument("--bad-rate", type=float, default=0.03,
                        help="share of sales messages that are deliberately broken")
    parser.add_argument("--seed", type=int, default=None, help="fix the random sequence")
    args = parser.parse_args()

    from kafka import KafkaProducer
    producer = KafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all", retries=5,
                             linger_ms=20, key_serializer=encode, value_serializer=encode)
    rng = random.Random(args.seed)
    counts = {"receipts": 0, "movements": 0, "broken": 0}

    def on_error(error):
        print("SEND FAILED:", error)

    try:
        while args.events == 0 or counts["receipts"] < args.events:
            now = datetime.now(timezone.utc)
            if rng.random() < args.bad_rate:
                bad = make_bad_sale(rng, now)
                producer.send(TOPIC_SALES, key="S00", value=bad).add_errback(on_error)
                counts["broken"] += 1
            else:
                sale, movements = build_sale(rng, now)
                producer.send(TOPIC_SALES, key=sale["store_id"], value=sale).add_errback(on_error)
                for movement in movements:
                    producer.send(TOPIC_INVENTORY, key=movement["store_id"],
                                  value=movement).add_errback(on_error)
                counts["receipts"] += 1
                counts["movements"] += len(movements)
            if rng.random() < 0.10:
                movement = build_stock_event(rng, now)
                producer.send(TOPIC_INVENTORY, key=movement["store_id"],
                              value=movement).add_errback(on_error)
                counts["movements"] += 1
            if (counts["receipts"] + counts["broken"]) % 50 == 0:
                print(f"sent so far: {counts}")
            time.sleep(1 / args.rate)
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        producer.flush()
        producer.close()
    print(f"done: {counts}")


if __name__ == "__main__":
    main()
