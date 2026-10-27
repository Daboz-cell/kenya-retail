# Kenya National Retail and Market Intelligence Platform

A complete data engineering platform that tracks what food and household goods cost across Kenya and evaluates retail operational performance against national and county market benchmarks.

---

## Architecture Overview

```
                      DATA INGESTION ARCHITECTURE (Milestone 1)

+-----------------------+     +------------------------+     +------------------------+
|  Synthetic Retail     |     |  KAMIS Portal (Kilimo) |     |  KNBS Monthly Report   |
|  Operational Data     |     |  Market Prices (Gov)   |     |  CPI & Inflation (Gov) |
+-----------+-----------+     +-----------+------------+     +-----------+------------+
            |                             |                              |
            v                             v                              v
  generate_retail_data.py        ingest_kamis.py               ingest_knbs_cpi.py
  (Deterministic seed,          (Watermark state,             (PDF table extraction,
   date-partitioned POS)         lookback deduplication)       retail benchmark map)
            |                             |                              |
            +-----------------------------+------------------------------+
                                          |
                                          v
                              RAW DATA LAKE (data/raw/)
            +-----------------------------+------------------------------+
            |                             |                              |
            v                             v                              v
   data/raw/synthetic/             data/raw/kamis/                 data/raw/knbs/
   ├── dimensions/                 ├── incoming/                  ├── manual/ (raw PDF)
   │   ├── stores.csv              ├── _state/watermark.json      ├── cpi_divisions.csv
   │   ├── products.csv            └── market_prices/             ├── commodity_retail_prices.csv
   │   └── suppliers.csv               └── date=YYYY-MM-DD/       ├── cpi_monthly_trend.csv
   ├── pos_transactions/                   └── part-0000.csv      └── commodity_benchmarks.csv
   │   └── date=YYYY-MM-DD/
   └── inventory_movements/
       └── date=YYYY-MM-DD/
```

---

## Milestone 1: Data Ingestion Pipelines

### 1. Synthetic Operational Data Pipeline
- **Script**: `ingestion/synthetic/generate_retail_data.py`
- **Description**: Generates realistic point-of-sale (POS) receipts, daily store traffic patterns, weekend/payday spikes, price drift, supplier deliveries (RESTOCK), and perishable shrinkage (WASTAGE).
- **County & Commodity Alignment**: Store locations and products align 1:1 with KAMIS and KNBS reporting standards (e.g. `Kilifi`, `Uasin-Gishu`, `Nakuru`, `Cow Milk(Processd)`, `Maize Flour`, `White Irish Potatoes`).
- **Idempotency**: Seed-based pseudo-random generation produces identical, reproducible datasets across runs.

### 2. KAMIS Market Prices Pipeline
- **Scripts**: `ingestion/kamis/download_kamis.py` and `ingestion/kamis/ingest_kamis.py`
- **Description**: Downloads daily wholesale and retail commodity prices across 40+ Kenya counties from the Ministry of Agriculture portal (`kamis.kilimo.go.ke`).
- **Incremental Logic**:
  - Tracks latest ingested dates per commodity in `data/raw/kamis/_state/watermark.json`.
  - Applies a 3-day lookback window (`LOOKBACK_DAYS = 3`) to reliably ingest late-arriving records.
  - Deduplicates on composite business key `(commodity, classification, grade, sex, market, county, date)`.

### 3. KNBS CPI & Inflation Pipeline
- **Script**: `ingestion/knbs/ingest_knbs_cpi.py`
- **Description**: Extracts and normalizes data from the official Kenya National Bureau of Statistics monthly CPI and inflation release PDF.
- **Parsed Data Assets**:
  - `cpi_divisions.csv`: 13 COICOP division index weights, 1-month % changes, and 12-month % changes.
  - `commodity_retail_prices.csv`: 24 national average commodity retail prices comparing current vs. previous month and year.
  - `cpi_monthly_trend.csv`: 13-month historical overall, core, and non-core CPI indices and inflation rates.
  - `commodity_benchmarks.csv`: Joins KNBS benchmark prices directly to our retail store product IDs (`P001` - `P012`).

---

## Quickstart: Running Milestone 1

### Prerequisites
Ensure your virtual environment is active and `poppler-utils` is installed:
```bash
source .venv/bin/activate
sudo apt install -y poppler-utils
pip install pandas requests
```

### Run All Ingestion Pipelines
Execute the unified master runner:
```bash
python3 scripts/run_all_ingestion.py
```

### Inspect Output Evidence
```bash
# Verify synthetic dimension and transaction files
ls -lh data/raw/synthetic/dimensions/
ls data/raw/synthetic/pos_transactions/ | head -5

# Verify KAMIS partitions & watermark
ls data/raw/kamis/market_prices/ | head -5
cat data/raw/kamis/_state/watermark.json

# Verify KNBS parsed outputs
head -5 data/raw/knbs/commodity_benchmarks.csv
head -5 data/raw/knbs/cpi_divisions.csv
```

---

## Roadmap

- [x] **Milestone 1: Data Ingestion** (Synthetic, KAMIS, KNBS)
- [ ] **Milestone 2: Apache Kafka** (Event streaming for POS & inventory)
- [ ] **Milestone 3: Apache Spark** (Bronze, Silver, Gold data lakehouse layers)
- [ ] **Milestone 4: Data Warehousing** (PostgreSQL dimensional model & analytical queries)
- [ ] **Milestone 5: Apache Airflow** (Orchestration, retry logic & DAGs)
- [ ] **Milestone 6: Data Quality** (Validation suites & schema enforcement)
- [ ] **Milestone 7: Deployment** (Docker compose & production monitoring)
- [ ] **Milestone 8: Documentation & Defense** (Architecture, presentation & final defense)
