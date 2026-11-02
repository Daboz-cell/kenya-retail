import json
import random
import sys
import tempfile
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kafka"))
sys.path.insert(0, str(ROOT / "kafka" / "producers"))
sys.path.insert(0, str(ROOT / "kafka" / "consumers"))

import pos_producer
import raw_landing
import stock_monitor
from common import TOPIC_ALERTS, TOPIC_INVENTORY, TOPIC_SALES, encode, validate_event

Record = namedtuple("Record", "offset timestamp key value")
NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def record(offset, value, key=b"S01", timestamp=NOW_MS):
    return Record(offset, timestamp, key, encode(value))


def test_generated_events_are_valid():
    rng = random.Random(1)
    for _ in range(300):
        sale, movements = pos_producer.build_sale(rng, NOW)
        assert validate_event(TOPIC_SALES, sale) is None
        for movement in movements:
            assert validate_event(TOPIC_INVENTORY, movement) is None
        assert validate_event(TOPIC_INVENTORY, pos_producer.build_stock_event(rng, NOW)) is None


def test_broken_events_are_rejected():
    rng = random.Random(2)
    reasons = set()
    for _ in range(60):
        bad = pos_producer.make_bad_sale(rng, NOW)
        _, dead = raw_landing.process_partition(TOPIC_SALES, 0, [record(0, bad)])
        assert len(dead) == 1
        reasons.add(dead[0]["reason"])
    assert len(reasons) == 3, reasons


def test_batch_file_name_is_stable_so_replay_overwrites():
    rng = random.Random(3)
    sale, _ = pos_producer.build_sale(rng, NOW)
    first = [record(40, sale), record(41, sale)]
    replay = [record(40, sale)]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        landed, _ = raw_landing.process_partition(TOPIC_SALES, 2, first)
        path_a = raw_landing.write_batch(root, TOPIC_SALES, 2, first, landed)
        landed, _ = raw_landing.process_partition(TOPIC_SALES, 2, replay)
        path_b = raw_landing.write_batch(root, TOPIC_SALES, 2, replay, landed)
        assert path_a == path_b
        assert path_a.name == "part-2-000000000040.jsonl"
        assert path_a.parent.name == "date=2026-10-27"
        assert len(path_a.read_text().splitlines()) == 1
        assert json.loads(path_a.read_text().splitlines()[0])["offset"] == 40
        assert not list(root.rglob("*.tmp"))


def test_all_invalid_batch_writes_no_file():
    with tempfile.TemporaryDirectory() as tmp:
        records = [record(0, b"not json")]
        landed, dead = raw_landing.process_partition(TOPIC_SALES, 0, records)
        assert raw_landing.write_batch(Path(tmp), TOPIC_SALES, 0, records, landed) is None
        assert len(dead) == 1 and landed == []


def test_stock_tracker_alerts_once_and_resets_after_restock():
    tracker = stock_monitor.StockTracker(opening_stock=10, reorder_level=4)

    def move(change, offset):
        event = {"store_id": "S01", "product_id": "P001", "quantity_change": change}
        return tracker.apply(event, 0, offset, NOW_MS)

    assert move(-3, 0) is None
    alert = move(-4, 1)
    assert alert["stock_level"] == 3 and alert["alert_id"] == "S01-P001-0-1"
    assert validate_event(TOPIC_ALERTS, alert) is None
    assert move(-1, 2) is None
    assert move(+50, 3) is None
    assert move(-50, 4)["stock_level"] == 2


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print(f"{len(tests)} tests passed")
