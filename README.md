# Kenya National Retail and Market Intelligence Platform

A solo data engineering capstone. It tracks what food and household goods cost across Kenya
(public market data) and how a retail chain performs against those prices.

## Status

| Module | Status |
|---|---|
| 1. Data ingestion | Complete, submitted for review |
| 2. Apache Kafka | Planned next |
| 3. Apache Spark (Bronze, Silver, Gold) | Planned |
| 4. PostgreSQL data warehouse | Planned |
| 5. Apache Airflow | Planned |
| 6. Data quality | Planned |
| 7. Deployment | Planned |
| 8. Documentation | In progress (this README) |

## Module 1: data ingestion

Three sources land untouched in a raw layer (data/raw). The raw layer keeps what the source said,
so later layers can always be rebuilt from it.

### Architecture

    Synthetic generator --> data/raw/synthetic/
                              dimensions/ (stores, products, suppliers)
                              pos_transactions/date=YYYY-MM-DD/
                              inventory_movements/date=YYYY-MM-DD/

    KAMIS Excel exports --> data/raw/kamis/incoming/ --> ingest_kamis.py
                              --> data/raw/kamis/market_prices/date=YYYY-MM-DD/
                              (state: data/raw/kamis/_state/watermark.json)

    KNBS CPI report PDF --> data/raw/knbs/incoming/ --> ingest_knbs.py
                              --> data/raw/knbs/<dataset>/report_month=YYYY-MM/
                              datasets: cpi_overall, cpi_divisions, retail_prices, core_noncore
                              (state: data/raw/knbs/_state/reports.json)

### Repository layout

    ingestion/synthetic/generate_retail_data.py   synthetic retail chain (12 stores, 12 products, 6 suppliers)
    ingestion/kamis/download_kamis.py             downloads KAMIS Excel exports politely
    ingestion/kamis/ingest_kamis.py               KAMIS ingestion with watermark and lookback
    ingestion/kamis/key_conflicts.py              reports natural keys that carry conflicting rows
    ingestion/kamis/list_products.py              lists KAMIS product ids
    ingestion/kamis/inspect_excel.py              prints the layout of an Excel export
    ingestion/knbs/ingest_knbs.py                 KNBS CPI report ingestion
    scripts/run_all_ingestion.py                  runs all three and prints what landed
    docker-compose.yml                            PostgreSQL service (used from Module 4)

### Setup and run

    sudo apt install -y python3-venv python3-pip poppler-utils
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

    python ingestion/kamis/download_kamis.py     # optional: refresh KAMIS exports (13 requests, 3 s apart)
    mkdir -p data/raw/knbs/incoming              # put each monthly KNBS CPI report PDF here
    python scripts/run_all_ingestion.py

The runner stops with an error if any dataset is empty.

### How each pipeline is incremental and re-runnable

| Source | Incremental because | Re-runnable because |
|---|---|---|
| Synthetic | run for new dates with --start and --end | each day is seeded by its date and its folder is overwritten, so a rerun gives identical files |
| KAMIS | a watermark (newest date per commodity) with a 3 day lookback skips old rows | exact duplicate rows are removed, output is sorted, files are written to a temporary name and renamed |
| KNBS | the SHA-256 hash of each PDF is stored; a known report is skipped | each report owns one folder, report_month=YYYY-MM, so a revised report overwrites only itself |

Re-runnability is checked by fingerprinting the output folder (md5 of every file), running the
pipeline again, and fingerprinting again. The two fingerprints match.

### Problems found while testing (and fixed)

1. KAMIS output changed between runs. The cause was a rule that kept one row per natural key
   (commodity, classification, grade, sex, market, county, date), while KAMIS holds 714 keys with
   several different rows. Raw now removes only exact duplicates and keeps conflicting rows;
   resolving them is a Silver layer rule.
2. A KAMIS file lost most of its rows because an earlier file in the same run had already moved the
   watermark. Every file is now judged against the watermark as it was at the start of the run.
3. An earlier KNBS parser wrote 0 rows and still reported success. It was replaced by a parser that
   validates its input (minimum row counts, division weights adding up to 100) and fails loudly.

### Data quality findings in KAMIS (to be handled in Silver)

- Prices are text with a unit (for example 50.00/Kg); a dash means missing.
- County spellings differ from official names (Uasin-Gishu, Muranga) and one county value is "test".
- Conflicting rows exist for one key, for example wholesale 1.00/Kg beside 200.00/Kg for the same market and day.
- The downloaded data has no Mombasa, Baringo or Homa Bay rows, so the synthetic coastal store is in Kilifi.

### Known limitations

- A KAMIS export is capped at 3,000 rows (the site's largest page size), newest first, so old history is truncated. This is enough for an incremental pipeline.
- KAMIS has no documented API. The site publishes no robots.txt. The downloader uses the site's own Excel export, 13 requests in total, 3 seconds apart, with an identified User-Agent.
- KNBS publishes the CPI as a PDF. Parsing text from a PDF is fragile, so the parser checks its own output and stops if the layout changes.
- Prices and quantities in the synthetic data are invented, only calibrated roughly to real prices.
