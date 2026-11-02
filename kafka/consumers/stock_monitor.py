import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import BOOTSTRAP, TOPIC_ALERTS, TOPIC_INVENTORY, encode, parse_and_validate

GROUP_ID = "stock-monitor"


class StockTracker:
    """Keeps a running stock level per (store, product) and spots low stock."""

    def __init__(self, opening_stock, reorder_level):
        self.opening_stock = opening_stock
        self.reorder_level = reorder_level
        self.levels = {}
        self.low = set()

    def apply(self, event, partition, offset, timestamp_ms):
        key = (event["store_id"], event["product_id"])
        level = self.levels.get(key, self.opening_stock) + event["quantity_change"]
        self.levels[key] = level
        if level <= self.reorder_level and key not in self.low:
            self.low.add(key)
            when = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            return {"alert_id": f"{key[0]}-{key[1]}-{partition}-{offset}",
                    "store_id": key[0], "product_id": key[1], "stock_level": level,
                    "reorder_level": self.reorder_level,
                    "alert_time": when.isoformat(timespec="seconds")}
        if level > self.reorder_level:
            self.low.discard(key)
        return None


def main():
    parser = argparse.ArgumentParser(description="Watch inventory events and raise low stock alerts")
    parser.add_argument("--opening-stock", type=int, default=100)
    parser.add_argument("--reorder-level", type=int, default=20)
    args = parser.parse_args()

    from kafka import KafkaConsumer, KafkaProducer
    consumer = KafkaConsumer(TOPIC_INVENTORY, bootstrap_servers=BOOTSTRAP, group_id=GROUP_ID,
                             enable_auto_commit=False, auto_offset_reset="earliest",
                             max_poll_records=500)
    producer = KafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all", retries=5,
                             key_serializer=encode, value_serializer=encode)
    tracker = StockTracker(args.opening_stock, args.reorder_level)
    seen = skipped = alerts = 0

    try:
        while True:
            for tp, records in consumer.poll(timeout_ms=1000).items():
                for record in records:
                    reason, event = parse_and_validate(TOPIC_INVENTORY, record.value)
                    if reason is not None:
                        skipped += 1
                        continue
                    seen += 1
                    alert = tracker.apply(event, tp.partition, record.offset, record.timestamp)
                    if alert:
                        producer.send(TOPIC_ALERTS, key=alert["store_id"], value=alert)
                        alerts += 1
                        print(f"LOW STOCK {alert['store_id']} {alert['product_id']}: "
                              f"{alert['stock_level']} left (reorder at {alert['reorder_level']})")
            producer.flush()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        consumer.close()
        producer.close()
    print(f"done: movements={seen} skipped={skipped} alerts={alerts}")


if __name__ == "__main__":
    main()
