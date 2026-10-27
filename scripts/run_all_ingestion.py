import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_DIR = PROJECT_ROOT / "data" / "raw" / "synthetic"
KAMIS_DIR = PROJECT_ROOT / "data" / "raw" / "kamis" / "market_prices"
KNBS_DIR = PROJECT_ROOT / "data" / "raw" / "knbs"


def run_step(step_name, command):
    print(f"\n{'='*70}")
    print(f"  STEP: {step_name}")
    print(f"  CMD : {' '.join(command)}")
    print(f"{'='*70}")
    res = subprocess.run(command, cwd=PROJECT_ROOT)
    if res.returncode != 0:
        print(f"[FAILED] Step '{step_name}' exited with code {res.returncode}")
        sys.exit(res.returncode)
    print(f"✓ Step '{step_name}' completed successfully.")


def print_milestone1_evidence():
    print(f"\n{'='*70}")
    print("  MILESTONE 1: DATA INGESTION EVIDENCE SUMMARY")
    print(f"{'='*70}")

    # 1. Synthetic Data Summary
    stores_file = SYNTHETIC_DIR / "dimensions" / "stores.csv"
    products_file = SYNTHETIC_DIR / "dimensions" / "products.csv"
    pos_parts = list((SYNTHETIC_DIR / "pos_transactions").glob("date=*/part-0000.csv"))
    inv_parts = list((SYNTHETIC_DIR / "inventory_movements").glob("date=*/part-0000.csv"))

    print("\n1. Synthetic Operational Retail Data:")
    print(f"   - Landing directory   : {SYNTHETIC_DIR}")
    print(f"   - Stores              : {stores_file} (exists={stores_file.exists()})")
    print(f"   - Products Catalog    : {products_file} (exists={products_file.exists()})")
    print(f"   - POS Sales Partitions: {len(pos_parts)} daily partitions")
    print(f"   - Inventory Partitions: {len(inv_parts)} daily partitions")

    # 2. KAMIS Data Summary
    kamis_parts = list(KAMIS_DIR.glob("date=*/part-0000.csv"))
    watermark_file = PROJECT_ROOT / "data" / "raw" / "kamis" / "_state" / "watermark.json"
    print("\n2. KAMIS Market Prices Data:")
    print(f"   - Landing directory   : {KAMIS_DIR}")
    print(f"   - Market Partitions   : {len(kamis_parts)} daily partitions")
    print(f"   - Watermark State     : {watermark_file} (incremental tracking active)")

    # 3. KNBS Data Summary
    div_file = KNBS_DIR / "cpi_divisions.csv"
    comm_file = KNBS_DIR / "commodity_retail_prices.csv"
    trend_file = KNBS_DIR / "cpi_monthly_trend.csv"
    bm_file = KNBS_DIR / "commodity_benchmarks.csv"
    print("\n3. KNBS Consumer Price Index & Inflation Data:")
    print(f"   - Landing directory   : {KNBS_DIR}")
    print(f"   - CPI Divisions       : {div_file} (exists={div_file.exists()})")
    print(f"   - Commodity Prices    : {comm_file} (exists={comm_file.exists()})")
    print(f"   - Monthly CPI Trend   : {trend_file} (exists={trend_file.exists()})")
    print(f"   - Mapped Benchmarks   : {bm_file} (exists={bm_file.exists()})")

    print(f"\n{'='*70}")
    print("  STATUS: Milestone 1 Data Ingestion Pipelines Ready for Defense!")
    print(f"{'='*70}\n")


def main():
    py = sys.executable

    # 1. Synthetic Retail Data Generation
    run_step(
        "Generate Synthetic Retail Data",
        [py, "ingestion/synthetic/generate_retail_data.py", "--start", "2026-08-01", "--end", "2026-10-26"]
    )

    # 2. Ingest KAMIS Drop-Folder Data
    run_step(
        "Ingest KAMIS Market Prices",
        [py, "ingestion/kamis/ingest_kamis.py"]
    )

    # 3. Ingest KNBS CPI PDF Data
    run_step(
        "Ingest KNBS CPI & Inflation Bulletin",
        [py, "ingestion/knbs/ingest_knbs_cpi.py"]
    )

    # Print Evidence Report
    print_milestone1_evidence()


if __name__ == "__main__":
    main()
