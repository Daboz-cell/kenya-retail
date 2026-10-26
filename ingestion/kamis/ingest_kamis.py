import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KAMIS_DIR = PROJECT_ROOT / "data" / "raw" / "kamis"
INCOMING = KAMIS_DIR / "incoming"
OUT_DIR = KAMIS_DIR / "market_prices"
STATE_FILE = KAMIS_DIR / "_state" / "watermark.json"

SHEET = "Market Prices"
EXPECTED = ["Commodity", "Classification", "Grade", "Sex", "Market",
            "Wholesale", "Retail", "Supply Volume", "County", "Date"]
COLUMNS = ["commodity", "classification", "grade", "sex", "market",
           "wholesale", "retail", "supply_volume", "county", "date"]
KEY = ["commodity", "classification", "grade", "sex", "market", "county", "date"]
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
LOOKBACK_DAYS = 3


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_FILE)


def read_export(path):
    df = pd.read_excel(path, sheet_name=SHEET, dtype=str, keep_default_na=False)
    if list(df.columns) != EXPECTED:
        raise ValueError(f"{path.name}: unexpected columns {list(df.columns)}")
    df.columns = COLUMNS
    df = df.apply(lambda col: col.str.strip())
    df["date"] = df["date"].str[:10]
    return df


def filter_new(df, state):
    cutoffs = {c: (date.fromisoformat(last) - timedelta(days=LOOKBACK_DAYS)).isoformat()
               for c, last in state.items()}
    cutoff = df["commodity"].map(lambda c: cutoffs.get(c, "0000-00-00"))
    is_valid = df["date"].str.match(DATE_RE)
    is_old = is_valid & (df["date"] < cutoff)
    return df[~is_old]


def write_partitions(df, source_name, ingested_at):
    if df.empty:
        return 0
    df = df.assign(source_file=source_name, ingested_at=ingested_at)
    df["date"] = df["date"].where(df["date"].str.match(DATE_RE), "unknown")
    for day, part in df.groupby("date"):
        target = OUT_DIR / f"date={day}" / "part-0000.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            old = pd.read_csv(target, dtype=str, keep_default_na=False)
            part = pd.concat([old, part], ignore_index=True)
        part = part.drop_duplicates(subset=COLUMNS, keep="first")
        part = part.drop_duplicates(subset=KEY, keep="last")
        part = part.sort_values(KEY)
        tmp = target.with_suffix(".tmp")
        part.to_csv(tmp, index=False)
        tmp.replace(target)
    return len(df)


def advance_watermark(state, df):
    good = df[df["date"].str.match(DATE_RE)]
    for commodity, newest in good.groupby("commodity")["date"].max().items():
        if newest > state.get(commodity, ""):
            state[commodity] = newest


def main():
    parser = argparse.ArgumentParser(description="Ingest KAMIS Excel exports")
    parser.add_argument("--reset", action="store_true",
                        help="forget the watermark and reload everything")
    args = parser.parse_args()

    INCOMING.mkdir(parents=True, exist_ok=True)
    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()

    state = load_state()
    files = sorted(INCOMING.glob("*.xls*"))
    if not files:
        print(f"No Excel files found in {INCOMING}")
        return

    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for path in files:
        raw = read_export(path)
        fresh = filter_new(raw, state)
        written = write_partitions(fresh, path.name, ingested_at)
        advance_watermark(state, raw)
        print(f"{path.name}: read {len(raw)}, skipped {len(raw) - len(fresh)} "
              f"older than watermark, processed {written}")

    save_state(state)
    print("Watermark:", json.dumps(state))
    print(f"Output folder: {OUT_DIR}")


if __name__ == "__main__":
    main()
