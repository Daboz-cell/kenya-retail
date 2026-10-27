import argparse
import csv
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNBS_DIR = PROJECT_ROOT / "data" / "raw" / "knbs"
INCOMING = KNBS_DIR / "incoming"
STATE_FILE = KNBS_DIR / "_state" / "reports.json"

MONTHS = {name: number for number, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

PRICE = r"\d[\d, ]*\.\d{2}"
CPI_RE = re.compile(
    r"overall\s+index\s+\w+\s+from\s+([\d.]+)\s+in\s+([A-Za-z]+)\s+(\d{4})\s+"
    r"to\s+([\d.]+)\s+in\s+([A-Za-z]+)\s+(\d{4}),?\s+resulting\s+in\s+a\s+monthly\s+"
    r"inflation\s+rate\s+of\s+(-?[\d.]+)\s+per\s+cent", re.I)
ANNUAL_RES = [
    re.compile(r"year-on-year\s+inflation\s+\w+\s+at\s+(-?[\d.]+)\s+per\s+cent", re.I),
    re.compile(r"Annual\s+consumer\s+price\s+inflation\s+was\s+(-?[\d.]+)\s+per\s+cent", re.I),
]
BASE_RE = re.compile(r"base\s+period,\s+which\s+for\s+the\s+current\s+CPI\s+is\s+"
                     r"([A-Za-z]+\s+\d{4})", re.I)
DIVISION_RE = re.compile(
    r"^\s*(?P<name>\S.*?)\s{2,}(?P<weight>\d+\.\d{4})\s+(?P<m>-?\d+\.\d)\s+(?P<y>-?\d+\.\d)\s*$")
PRICE_RE = re.compile(
    rf"^\s*(?P<name>\S.*?)\s{{2,}}(?P<qty>\d+)\s+(?P<unit>[A-Za-z]+)\s+"
    rf"(?P<p_year>{PRICE})\s+(?P<p_prev>{PRICE})\s+(?P<p_cur>{PRICE})\s+"
    rf"(?P<c_month>-?\d+\.\d)\s+(?P<c_year>-?\d+\.\d)\s*$")
CORE_RE = re.compile(
    r"^\s*(?P<period>[A-Z][a-z]{2}-\d{2})\s+(?P<ci>\d+\.\d+)\s+(?P<cinf>-?\d+\.\d+)\s+"
    r"(?P<ni>\d+\.\d+)\s+(?P<ninf>-?\d+\.\d+)\s*$")

SCHEMAS = {
    "cpi_overall": ["report_month", "previous_month", "previous_cpi", "current_month",
                    "current_cpi", "monthly_inflation_pct", "annual_inflation_pct",
                    "base_period", "source_file", "report_sha256"],
    "cpi_divisions": ["report_month", "division", "weight_pct", "change_month_pct",
                      "change_year_pct", "source_file", "report_sha256"],
    "retail_prices": ["report_month", "commodity", "quantity", "unit", "price_year_ago",
                      "price_prev_month", "price_current", "change_month_pct",
                      "change_year_pct", "source_file", "report_sha256"],
    "core_noncore": ["report_month", "period", "core_index", "core_inflation",
                     "noncore_index", "noncore_inflation", "source_file", "report_sha256"],
}


def extract_text(path):
    try:
        result = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                                capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise SystemExit("pdftotext not found: run  sudo apt install -y poppler-utils")
    return result.stdout


def month_key(name, year):
    return f"{int(year)}-{MONTHS[name.capitalize()]:02d}"


def parse_report(text, source_file, sha):
    flat = " ".join(text.split())
    match = CPI_RE.search(flat)
    if not match:
        raise ValueError(f"{source_file}: overall CPI sentence not found")
    prev_cpi, prev_name, prev_year, cur_cpi, cur_name, cur_year, monthly = match.groups()
    report_month = month_key(cur_name, cur_year)

    annual = None
    for pattern in ANNUAL_RES:
        found = pattern.search(flat)
        if found:
            annual = found.group(1)
            break
    if annual is None:
        raise ValueError(f"{source_file}: annual inflation sentence not found")
    base = BASE_RE.search(flat)

    lineage = {"source_file": source_file, "report_sha256": sha}
    tables = {"cpi_overall": [{
        "report_month": report_month,
        "previous_month": month_key(prev_name, prev_year), "previous_cpi": prev_cpi,
        "current_month": report_month, "current_cpi": cur_cpi,
        "monthly_inflation_pct": monthly, "annual_inflation_pct": annual,
        "base_period": base.group(1) if base else "", **lineage}],
        "cpi_divisions": [], "retail_prices": [], "core_noncore": []}

    last_text_line = ""
    for line in text.splitlines():
        row = PRICE_RE.match(line)
        if row:
            name = row["name"].strip()
            if name[0].islower():
                name = f"{last_text_line} {name}".strip()
            clean = {k: row[k].replace(" ", "") for k in
                     ("p_year", "p_prev", "p_cur", "c_month", "c_year")}
            tables["retail_prices"].append({
                "report_month": report_month, "commodity": name,
                "quantity": row["qty"], "unit": row["unit"],
                "price_year_ago": clean["p_year"], "price_prev_month": clean["p_prev"],
                "price_current": clean["p_cur"], "change_month_pct": clean["c_month"],
                "change_year_pct": clean["c_year"], **lineage})
        elif DIVISION_RE.match(line):
            row = DIVISION_RE.match(line)
            tables["cpi_divisions"].append({
                "report_month": report_month, "division": row["name"].strip(),
                "weight_pct": row["weight"], "change_month_pct": row["m"],
                "change_year_pct": row["y"], **lineage})
        elif CORE_RE.match(line):
            row = CORE_RE.match(line)
            tables["core_noncore"].append({
                "report_month": report_month, "period": row["period"],
                "core_index": row["ci"], "core_inflation": row["cinf"],
                "noncore_index": row["ni"], "noncore_inflation": row["ninf"], **lineage})
        if line.strip():
            last_text_line = line.strip()
    return report_month, tables


def validate(source_file, tables):
    minimum = {"cpi_divisions": 14, "retail_prices": 15, "core_noncore": 13}
    for name, needed in minimum.items():
        if len(tables[name]) < needed:
            raise ValueError(f"{source_file}: {name} has {len(tables[name])} rows, "
                             f"expected at least {needed}")
    weights = [float(r["weight_pct"]) for r in tables["cpi_divisions"]
               if r["division"] != "Total"]
    if abs(sum(weights) - 100) > 0.05:
        raise ValueError(f"{source_file}: division weights add up to {sum(weights):.4f}")


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_FILE)


def main():
    parser = argparse.ArgumentParser(description="Ingest KNBS CPI report PDFs")
    parser.add_argument("--reset", action="store_true",
                        help="forget which reports were ingested and process all again")
    args = parser.parse_args()

    INCOMING.mkdir(parents=True, exist_ok=True)
    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()

    state = load_state()
    files = sorted(INCOMING.glob("*.pdf"))
    if not files:
        print(f"No PDF files found in {INCOMING}")
        return

    for path in files:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        report_month, tables = parse_report(extract_text(path), path.name, sha)
        if state.get(report_month, {}).get("sha256") == sha:
            print(f"{path.name}: report {report_month} already ingested, skipped")
            continue
        validate(path.name, tables)
        for dataset, rows in tables.items():
            target = KNBS_DIR / dataset / f"report_month={report_month}" / "part-0000.csv"
            write_csv(target, SCHEMAS[dataset], rows)
        state[report_month] = {
            "sha256": sha, "source_file": path.name,
            "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        counts = ", ".join(f"{name}={len(rows)}" for name, rows in tables.items())
        print(f"{path.name}: report {report_month} ingested ({counts})")

    save_state(state)
    print("Reports on record:", ", ".join(sorted(state)))
    print(f"Output folder: {KNBS_DIR}")


if __name__ == "__main__":
    main()
