import json
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
STREAM_DIR = PROJECT_ROOT / "data" / "raw" / "streaming"

TOPIC_SALES = "retail.pos.sales"
TOPIC_INVENTORY = "retail.inventory.movements"
TOPIC_ALERTS = "retail.stock.alerts"
TOPIC_DEAD_LETTER = "retail.dead_letter"
DATA_TOPICS = [TOPIC_SALES, TOPIC_INVENTORY, TOPIC_ALERTS]

STORE_RE = re.compile(r"^S\d{2}$")
PRODUCT_RE = re.compile(r"^P\d{3}$")
MOVEMENT_TYPES = {"SALE", "RESTOCK", "WASTAGE"}
PAYMENT_METHODS = {"MPESA", "CASH", "CARD"}

REQUIRED = {
    TOPIC_SALES: ["event_id", "transaction_id", "store_id", "sold_at",
                  "payment_method", "lines"],
    TOPIC_INVENTORY: ["event_id", "movement_id", "store_id", "product_id",
                      "movement_type", "quantity_change", "moved_at"],
    TOPIC_ALERTS: ["alert_id", "store_id", "product_id", "stock_level",
                   "reorder_level", "alert_time"],
}


def encode(value):
    if isinstance(value, bytes):
        return value
    return json.dumps(value, sort_keys=True).encode("utf-8")


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_event(topic, event):
    """Return None when the event is valid, otherwise a short reason."""
    if not isinstance(event, dict):
        return "event is not a JSON object"
    missing = [name for name in REQUIRED[topic] if name not in event]
    if missing:
        return "missing fields: " + ", ".join(missing)
    if not STORE_RE.match(str(event["store_id"])):
        return f"bad store_id: {event['store_id']!r}"

    if topic == TOPIC_SALES:
        if event["payment_method"] not in PAYMENT_METHODS:
            return f"bad payment_method: {event['payment_method']!r}"
        lines = event["lines"]
        if not isinstance(lines, list) or not lines:
            return "lines must be a non-empty list"
        for line in lines:
            if not isinstance(line, dict) or not PRODUCT_RE.match(str(line.get("product_id"))):
                return "line has a bad product_id"
            if not isinstance(line.get("quantity"), int) or line["quantity"] <= 0:
                return "line quantity must be a positive whole number"
            if not is_number(line.get("unit_price")) or line["unit_price"] <= 0:
                return "line unit_price must be a positive number"
    elif topic == TOPIC_INVENTORY:
        if not PRODUCT_RE.match(str(event["product_id"])):
            return f"bad product_id: {event['product_id']!r}"
        if event["movement_type"] not in MOVEMENT_TYPES:
            return f"bad movement_type: {event['movement_type']!r}"
        change = event["quantity_change"]
        if not isinstance(change, int) or isinstance(change, bool) or change == 0:
            return "quantity_change must be a non-zero whole number"
    else:
        if not PRODUCT_RE.match(str(event["product_id"])):
            return f"bad product_id: {event['product_id']!r}"
    return None


def parse_and_validate(topic, raw):
    """Decode raw message bytes. Returns (reason, event); reason is None when valid."""
    try:
        event = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return "message is not valid JSON", None
    return validate_event(topic, event), event
