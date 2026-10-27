import argparse
import csv
import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNBS_DIR = PROJECT_ROOT / "data" / "raw" / "knbs"
MANUAL_DIR = KNBS_DIR / "manual"

# Mapping from KNBS Table 3 commodity names to our retail store product catalog & KAMIS
COMMODITY_MAPPING = {
    "Maize Flour - Sifted": {
        "product_id": "P001",
        "catalog_product_name": "Maize flour 2kg",
        "kamis_commodity": "Maize Flour",
    },
    "Wheat Flour-White": {
        "product_id": "P003",
        "catalog_product_name": "Wheat flour 2kg",
        "kamis_commodity": "Wheat Flour",
    },
    "Cooking Oil (Salad)": {
        "product_id": "P005",
        "catalog_product_name": "Cooking oil 1L",
        "kamis_commodity": "Sunflower Oil",
    },
    "Beans": {
        "product_id": "P006",
        "catalog_product_name": "Beans 1kg",
        "kamis_commodity": "Beans Rosecoco",
    },
    "Tomatoes": {
        "product_id": "P007",
        "catalog_product_name": "Tomatoes 1kg",
        "kamis_commodity": "Tomatoes",
    },
    "Potatoes (Irish)": {
        "product_id": "P009",
        "catalog_product_name": "Irish potatoes 1kg",
        "kamis_commodity": "White Irish Potatoes",
    },
    "Cabbages": {
        "product_id": "P010",
        "catalog_product_name": "Cabbage 1kg",
        "kamis_commodity": "Cabbages",
    },
    "Kale-Sukuma Wiki": {
        "product_id": "P011",
        "catalog_product_name": "Kale bunch",
        "kamis_commodity": "Kales/Sukuma Wiki",
    },
    "Fresh packeted cow milk": {
        "product_id": "P012",
        "catalog_product_name": "Milk 500ml",
        "kamis_commodity": "Cow Milk(Processd)",
    },
}

# Overall CPI and Inflation series from KNBS Figures 1 & 2
OVERALL_CPI_SERIES = {
    "Sep-25": {"overall_cpi": 146.56, "overall_inflation_pct": 4.6},
    "Oct-25": {"overall_cpi": 146.84, "overall_inflation_pct": 4.6},
    "Nov-25": {"overall_cpi": 147.08, "overall_inflation_pct": 4.5},
    "Dec-25": {"overall_cpi": 148.02, "overall_inflation_pct": 4.5},
    "Jan-26": {"overall_cpi": 148.96, "overall_inflation_pct": 4.4},
    "Feb-26": {"overall_cpi": 149.20, "overall_inflation_pct": 4.3},
    "Mar-26": {"overall_cpi": 150.00, "overall_inflation_pct": 4.4},
    "Apr-26": {"overall_cpi": 152.15, "overall_inflation_pct": 5.6},
    "May-26": {"overall_cpi": 154.56, "overall_inflation_pct": 6.7},
    "Jun-26": {"overall_cpi": 154.91, "overall_inflation_pct": 6.4},
    "Jul-26": {"overall_cpi": 155.20, "overall_inflation_pct": 6.5},
    "Aug-26": {"overall_cpi": 155.85, "overall_inflation_pct": 6.6},
    "Sep-26": {"overall_cpi": 156.47, "overall_inflation_pct": 6.8},
}

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def find_pdf_file(override_path=None):
    if override_path:
        p = Path(override_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Specified PDF not found: {override_path}")

    candidates = sorted(MANUAL_DIR.glob("*.pdf"), key=lambda f: f.stat().st_mtime, reverse=True)
    # Prefer files with "Consumer" or "Inflation" or "CPI"
    for cand in candidates:
        name_lower = cand.name.lower()
        if "consumer" in name_lower or "cpi" in name_lower or "inflation" in name_lower:
            return cand
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"No PDF file found in {MANUAL_DIR}")


def extract_text_from_pdf(pdf_path):
    cmd = ["pdftotext", "-layout", str(pdf_path), "-"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return res.stdout
    except FileNotFoundError:
        # Fallback if pypdf is installed
        try:
            import pypdf
            reader = pypdf.PdfReader(str(pdf_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise RuntimeError("Neither 'pdftotext' (poppler-utils) nor 'pypdf' is available.")


def parse_table_1_divisions(text, report_date="2026-09-30"):
    """
    Parses Table 1: One and Twelve-Month Percentage Changes in Consumer Price Indices
    """
    rows = []
    in_table = False
    pattern = re.compile(r"^(.*?)\s+(\d{1,3}\.\d{4})\s+([\-\+]?\d+\.\d+)\s+([\-\+]?\d+\.\d+)$")

    for line in text.splitlines():
        line = line.strip()
        if "Table 1:" in line:
            in_table = True
            continue
        if in_table:
            if line.startswith("Figure 3:") or line.startswith("Table 2:"):
                break
            match = pattern.match(line)
            if match:
                division, weight, mom, yoy = match.groups()
                division = division.strip()
                if division.lower() == "total":
                    continue
                rows.append({
                    "report_date": report_date,
                    "division_name": division,
                    "weight_pct": float(weight),
                    "mom_change_pct": float(mom),
                    "yoy_change_pct": float(yoy),
                })
    return rows


def parse_table_3_commodities(text, report_date="2026-09-30"):
    """
    Parses Table 3: National Average Retail Prices of Selected Commodities
    """
    rows = []
    in_table = False

    # Regex for a commodity row:
    # Commodity Name | Qty | Unit | Price Sep 25 | Price Aug 26 | Price Sep 26 | MoM % | YoY %
    # Notice numbers can contain spaces or commas: e.g. "1 ,274.06" or "5,597.16"
    pattern = re.compile(
        r"^(.*?)\s+(\d+)\s+([A-Za-z]+)\s+([\d\s,]+\.\d{2})\s+([\d\s,]+\.\d{2})\s+([\d\s,]+\.\d{2})\s+([\-\+]?\d+\.\d+)\s+([\-\+]?\d+\.\d+)$"
    )

    clean_lines = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "Table 3:" in line:
            in_table = True
            i += 1
            continue
        if in_table:
            if line.startswith("Figure 5:") or line.startswith("Table 4:"):
                break
            # Handle multi-line commodity names like "Country Bus /Matatu Fare (Isiolo \n to Nairobi)"
            if line and not pattern.match(line):
                if i + 1 < len(lines):
                    combined = line + " " + lines[i + 1].strip()
                    if pattern.match(combined):
                        clean_lines.append(combined)
                        i += 2
                        continue
            if line:
                clean_lines.append(line)
        i += 1

    def clean_num(s):
        return float(s.replace(" ", "").replace(",", ""))

    for line in clean_lines:
        match = pattern.match(line)
        if match:
            name, qty, unit, p_25, p_aug, p_sep, mom, yoy = match.groups()
            name = re.sub(r"\s+", " ", name).strip()
            rows.append({
                "report_date": report_date,
                "commodity_name": name,
                "quantity": int(qty),
                "unit": unit.strip(),
                "avg_price_sep_2025": clean_num(p_25),
                "avg_price_aug_2026": clean_num(p_aug),
                "avg_price_sep_2026": clean_num(p_sep),
                "mom_pct_change": float(mom),
                "yoy_pct_change": float(yoy),
            })
    return rows


def parse_table_4_core_inflation(text):
    """
    Parses Table 4: Core and Non-Core Index and Inflation
    Combines with OVERALL_CPI_SERIES to give complete monthly trend.
    """
    rows = []
    in_table = False
    pattern = re.compile(
        r"^([A-Za-z]{3}-\d{2})\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)$"
    )

    for line in text.splitlines():
        line = line.strip()
        if "Table 4:" in line:
            in_table = True
            continue
        if in_table:
            if line.startswith("Contribution of") or line.startswith("Table 5:"):
                break
            match = pattern.match(line)
            if match:
                period, core_idx, core_inf, non_core_idx, non_core_inf = match.groups()
                mon, yr = period.split("-")
                iso_month = f"20{yr}-{MONTH_MAP.get(mon, '01')}"
                overall = OVERALL_CPI_SERIES.get(period, {})
                rows.append({
                    "period": period,
                    "year_month": iso_month,
                    "overall_cpi": overall.get("overall_cpi", ""),
                    "overall_inflation_pct": overall.get("overall_inflation_pct", ""),
                    "core_index": float(core_idx),
                    "core_inflation_pct": float(core_inf),
                    "non_core_index": float(non_core_idx),
                    "non_core_inflation_pct": float(non_core_inf),
                })
    return rows


def build_commodity_benchmarks(commodity_rows):
    """
    Joins KNBS retail commodities with our store catalog product_id and KAMIS commodity.
    """
    benchmarks = []
    for r in commodity_rows:
        mapping = COMMODITY_MAPPING.get(r["commodity_name"])
        if mapping:
            benchmarks.append({
                "product_id": mapping["product_id"],
                "catalog_product_name": mapping["catalog_product_name"],
                "kamis_commodity": mapping["kamis_commodity"],
                "knbs_commodity_name": r["commodity_name"],
                "knbs_quantity": r["quantity"],
                "knbs_unit": r["unit"],
                "knbs_price_sep_2025": r["avg_price_sep_2025"],
                "knbs_price_aug_2026": r["avg_price_aug_2026"],
                "knbs_price_sep_2026": r["avg_price_sep_2026"],
                "knbs_mom_change_pct": r["mom_pct_change"],
                "knbs_yoy_change_pct": r["yoy_pct_change"],
            })
    return benchmarks


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def extract_report_date(text):
    match = re.search(r"Released on:\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", text, re.IGNORECASE)
    if match:
        day, month_name, year = match.groups()
        mon = MONTH_MAP.get(month_name[:3].capitalize(), "09")
        return f"{year}-{mon}-{int(day):02d}"
    return "2026-09-30"


def main():
    parser = argparse.ArgumentParser(description="Ingest and parse KNBS CPI bulletin PDF")
    parser.add_argument("--pdf", help="path to the KNBS CPI PDF report")
    parser.add_argument("--report-date", help="Report release date (auto-detected if omitted)")
    args = parser.parse_args()

    pdf_path = find_pdf_file(args.pdf)
    print(f"Reading KNBS report from: {pdf_path}")

    text = extract_text_from_pdf(pdf_path)
    report_date = args.report_date or extract_report_date(text)
    print(f"Report Date: {report_date}")

    # 1. Parse Table 1: COICOP Divisions
    divisions = parse_table_1_divisions(text, report_date=report_date)
    div_fields = ["report_date", "division_name", "weight_pct", "mom_change_pct", "yoy_change_pct"]
    n_div = write_csv(KNBS_DIR / "cpi_divisions.csv", div_fields, divisions)

    # 2. Parse Table 3: Commodity Average Retail Prices
    commodities = parse_table_3_commodities(text, report_date=report_date)
    comm_fields = [
        "report_date", "commodity_name", "quantity", "unit",
        "avg_price_sep_2025", "avg_price_aug_2026", "avg_price_sep_2026",
        "mom_pct_change", "yoy_pct_change"
    ]
    n_comm = write_csv(KNBS_DIR / "commodity_retail_prices.csv", comm_fields, commodities)

    # 3. Parse Table 4 & Figures 1/2: Monthly CPI & Inflation Trends
    monthly = parse_table_4_core_inflation(text)
    trend_fields = [
        "period", "year_month", "overall_cpi", "overall_inflation_pct",
        "core_index", "core_inflation_pct", "non_core_index", "non_core_inflation_pct"
    ]
    n_trend = write_csv(KNBS_DIR / "cpi_monthly_trend.csv", trend_fields, monthly)

    # 4. Map to Retail Store Catalog benchmarks
    benchmarks = build_commodity_benchmarks(commodities)
    bm_fields = [
        "product_id", "catalog_product_name", "kamis_commodity", "knbs_commodity_name",
        "knbs_quantity", "knbs_unit", "knbs_price_sep_2025", "knbs_price_aug_2026",
        "knbs_price_sep_2026", "knbs_mom_change_pct", "knbs_yoy_change_pct"
    ]
    n_bm = write_csv(KNBS_DIR / "commodity_benchmarks.csv", bm_fields, benchmarks)

    print("\n--- INGESTION SUMMARY ---")
    print(f"✓ COICOP Divisions parsed: {n_div} -> {KNBS_DIR / 'cpi_divisions.csv'}")
    print(f"✓ Commodity Retail Prices parsed: {n_comm} -> {KNBS_DIR / 'commodity_retail_prices.csv'}")
    print(f"✓ Monthly CPI Trend parsed: {n_trend} -> {KNBS_DIR / 'cpi_monthly_trend.csv'}")
    print(f"✓ Mapped Retail Benchmarks: {n_bm} -> {KNBS_DIR / 'commodity_benchmarks.csv'}")


if __name__ == "__main__":
    main()
