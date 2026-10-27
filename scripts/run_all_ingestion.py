import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW = PROJECT_ROOT / "data" / "raw"

STEPS = [
    ("Synthetic retail data",
     ["ingestion/synthetic/generate_retail_data.py", "--start", "2026-08-01"]),
    ("KAMIS market prices", ["ingestion/kamis/ingest_kamis.py"]),
    ("KNBS CPI reports", ["ingestion/knbs/ingest_knbs.py"]),
]

CHECKS = [
    ("Synthetic POS sale lines", RAW / "synthetic" / "pos_transactions", "date=*/part-0000.csv"),
    ("Synthetic stock movements", RAW / "synthetic" / "inventory_movements", "date=*/part-0000.csv"),
    ("KAMIS market prices", RAW / "kamis" / "market_prices", "date=*/part-0000.csv"),
    ("KNBS overall CPI", RAW / "knbs" / "cpi_overall", "report_month=*/part-0000.csv"),
    ("KNBS CPI divisions", RAW / "knbs" / "cpi_divisions", "report_month=*/part-0000.csv"),
    ("KNBS retail prices", RAW / "knbs" / "retail_prices", "report_month=*/part-0000.csv"),
    ("KNBS core and non-core", RAW / "knbs" / "core_noncore", "report_month=*/part-0000.csv"),
]


def run_step(name, args):
    print(f"\n=== STEP: {name}")
    result = subprocess.run([sys.executable, *args], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"FAILED: step '{name}' exited with code {result.returncode}")
        sys.exit(result.returncode)


def count_rows(folder, pattern):
    files = sorted(folder.glob(pattern))
    rows = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            rows += sum(1 for _ in f) - 1
    return len(files), rows


def main():
    for name, args in STEPS:
        run_step(name, args)

    print("\n=== EVIDENCE: what actually landed")
    empty = []
    for label, folder, pattern in CHECKS:
        partitions, rows = count_rows(folder, pattern)
        print(f"{label:28} partitions={partitions:5}  rows={rows:8}")
        if rows == 0:
            empty.append(label)

    if empty:
        print("\nFAILED: nothing landed for: " + ", ".join(empty))
        sys.exit(1)
    print("\nOK: every dataset has data")


if __name__ == "__main__":
    main()
