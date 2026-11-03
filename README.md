# Kenya National Retail and Market Intelligence Platform

A solo data engineering capstone. It tracks what food and household goods cost across Kenya
(public market data) and how a retail chain performs against those prices.

## Status

| Module | Status |
|---|---|
| 1. Data ingestion | Complete, submitted for review |
| 2. Apache Kafka | Complete, submitted for review |
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

## Module 2: Apache Kafka

Live sales and stock events flow through a single Kafka broker (version 4.3.1, KRaft mode, container
kr_kafka) and land as raw JSON Lines files in data/raw/streaming.

### Topics

| Topic | Key | Partitions | Written by | Read by (consumer group) |
|---|---|---|---|---|
| retail.pos.sales | store_id | 3 | kafka/producers/pos_producer.py | raw-landing |
| retail.inventory.movements | store_id | 3 | kafka/producers/pos_producer.py | raw-landing, stock-monitor |
| retail.stock.alerts | store_id | 1 | kafka/consumers/stock_monitor.py | raw-landing |
| retail.dead_letter | source topic | 1 | kafka/consumers/raw_landing.py | inspected by hand |

### Event flow

    POS producer --> retail.pos.sales ----------------+
          +-------> retail.inventory.movements ------+--> raw-landing group --> data/raw/streaming/<topic>/date=.../part-<partition>-<first offset>.jsonl
                          |                          |          +-- invalid messages --> retail.dead_letter
                          +--> stock-monitor group --> retail.stock.alerts --+

### Run

    docker compose --profile streaming up -d kafka
    ./kafka/create_topics.sh
    python kafka/consumers/stock_monitor.py --opening-stock 12 --reorder-level 8     # terminal 1
    python kafka/producers/pos_producer.py --events 200 --rate 10 --seed 7           # terminal 2
    python kafka/consumers/raw_landing.py --drain
    python tests/test_streaming_logic.py

### Design decisions

- Messages are keyed by store_id, so one store's events stay in order inside a partition.
- The two busy topics have 3 partitions so up to 3 consumers in one group can share the work.
  Replication factor is 1 because there is one broker; production would use 3.
- Two consumer groups read the inventory topic independently: raw-landing stores everything,
  stock-monitor keeps live stock levels and publishes low stock alerts.
- Delivery is at-least-once: the landing consumer commits offsets only after its file is written,
  and the file name depends only on partition and first offset, so a replay overwrites the same
  file instead of duplicating events.
- Messages that fail validation go to the dead letter topic with the reason; the pipeline keeps running.
- The stock monitor does not commit offsets. After a restart it replays the topic and rebuilds its
  stock state; alert ids are deterministic so repeated alerts can be deduplicated.

### Test results

- 5 unit tests pass (event validity, dead letter routing, stable file names on replay, stock alerts).
- Run 1: 200 receipts, 705 stock movements, 5 broken messages produced; 1,035 events landed
  (200 sales, 705 movements, 130 alerts) and 5 dead letters.
- Run 2: 600 receipts, 2,125 movements, 21 broken produced; 2,725 events landed and 21 dead letters.
- In every landed topic the number of rows equals the number of unique ids (no duplicates), and
  consumer lag is 0 on every partition.

### Known limitations

- Landing live creates many small files; a Spark compaction step handles this in Silver.
- Streaming timestamps are UTC with an offset, while the batch synthetic data has no time zone;
  Silver normalises both.
- Single broker, no security (plain text listeners), JSON without a schema registry.
- Stock monitor assumes an opening stock per store and product.
