import argparse
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://kamis.kilimo.go.ke/site/market"
HEADERS = {"User-Agent": "kenya-retail-capstone (student data engineering project)"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INCOMING = PROJECT_ROOT / "data" / "raw" / "kamis" / "incoming"
SHEET = "Market Prices"
DELAY_SECONDS = 3

PRODUCTS = {
    1: "Dry Maize",
    249: "Maize Flour",
    4: "Rice",
    265: "Wheat Flour",
    240: "Sunflower Oil",
    64: "Beans Rosecoco",
    61: "Tomatoes",
    158: "Dry Onions",
    163: "White Irish Potatoes",
    58: "Cabbages",
    154: "Kales/Sukuma Wiki",
    153: "Cow Milk (Processed)",
    72: "Eggs",
}


def download_product(product_id, per_page):
    params = {"product": product_id, "per_page": per_page, "export": "excel"}
    response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=120)
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise ValueError("response is not an Excel file")
    target = INCOMING / f"kamis_product_{product_id}.xlsx"
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(response.content)
    tmp.replace(target)
    return target


def summarise(path, per_page):
    df = pd.read_excel(path, sheet_name=SHEET, dtype=str, keep_default_na=False)
    rows = len(df)
    if rows == 0:
        print("  rows=0 (empty export)")
        return
    dates = df["Date"].str[:10]
    print(f"  rows={rows}  oldest={dates.min()}  newest={dates.max()}  "
          f"markets={df['Market'].nunique()}")
    if rows >= per_page:
        print(f"  WARNING: rows equal the page size ({per_page}); "
              "the export may be truncated and more pages may exist")


def main():
    parser = argparse.ArgumentParser(description="Download KAMIS exports politely")
    parser.add_argument("--products", default=",".join(str(p) for p in PRODUCTS),
                        help="comma separated KAMIS product ids")
    parser.add_argument("--per-page", type=int, default=3000)
    args = parser.parse_args()

    ids = [int(p) for p in args.products.split(",")]
    INCOMING.mkdir(parents=True, exist_ok=True)

    for n, product_id in enumerate(ids):
        if n > 0:
            time.sleep(DELAY_SECONDS)
        print(f"[{product_id}] {PRODUCTS.get(product_id, 'unknown product')}")
        try:
            path = download_product(product_id, args.per_page)
            summarise(path, args.per_page)
        except (requests.RequestException, ValueError, KeyError) as error:
            print(f"  FAILED: {error}")


if __name__ == "__main__":
    main()
