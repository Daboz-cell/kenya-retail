import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import (BOOTSTRAP, DATA_TOPICS, STREAM_DIR, TOPIC_DEAD_LETTER, encode,
                    parse_and_validate)

GROUP_ID = "raw-landing"


def process_partition(topic, partition, records):
    """Split one partition's records into landed envelopes and dead letters."""
    landed, dead = [], []
    for record in records:
        reason, event = parse_and_validate(topic, record.value)
        if reason is None:
            landed.append({"topic": topic, "partition": partition, "offset": record.offset,
                           "timestamp_ms": record.timestamp,
                           "key": record.key.decode("utf-8") if record.key else None,
                           "value": event})
        else:
            dead.append({"reason": reason, "topic": topic, "partition": partition,
                         "offset": record.offset,
                         "raw": record.value.decode("utf-8", errors="replace")})
    return landed, dead


def write_batch(root, topic, partition, records, landed):
    """Write one batch file. Its name depends only on partition and first offset."""
    if not landed:
        return None
    first = records[0]
    day = datetime.fromtimestamp(first.timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    path = root / topic / f"date={day}" / f"part-{partition}-{first.offset:012d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for envelope in landed:
            f.write(json.dumps(envelope, sort_keys=True) + "\n")
    tmp.replace(path)
    return path


def main():
    parser = argparse.ArgumentParser(description="Land Kafka events as raw JSON lines files")
    parser.add_argument("--drain", action="store_true",
                        help="exit after 5 seconds without new messages")
    args = parser.parse_args()

    from kafka import KafkaConsumer, KafkaProducer
    consumer = KafkaConsumer(*DATA_TOPICS, bootstrap_servers=BOOTSTRAP, group_id=GROUP_ID,
                             enable_auto_commit=False, auto_offset_reset="earliest",
                             max_poll_records=500)
    dead_letter = KafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all", retries=5,
                                key_serializer=encode, value_serializer=encode)
    totals = {"landed": 0, "dead": 0, "files": 0}
    idle_since = time.monotonic()

    try:
        while True:
            batches = consumer.poll(timeout_ms=1000)
            if not batches:
                if args.drain and time.monotonic() - idle_since > 5:
                    break
                continue
            idle_since = time.monotonic()
            for tp, records in batches.items():
                landed, dead = process_partition(tp.topic, tp.partition, records)
                if write_batch(STREAM_DIR, tp.topic, tp.partition, records, landed):
                    totals["files"] += 1
                for letter in dead:
                    dead_letter.send(TOPIC_DEAD_LETTER, key=tp.topic, value=letter)
                totals["landed"] += len(landed)
                totals["dead"] += len(dead)
            dead_letter.flush()
            consumer.commit()
            print(f"landed={totals['landed']} dead_letters={totals['dead']} "
                  f"files={totals['files']}")
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        consumer.close()
        dead_letter.close()
    print(f"done: {totals}")


if __name__ == "__main__":
    main()
