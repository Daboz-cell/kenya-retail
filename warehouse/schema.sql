-- Kenya Retail Data Platform Schema
-- Target Database: retail_dw (PostgreSQL 16)

-- 1. Create Schemas
CREATE SCHEMA IF NOT EXISTS raw_retail;
CREATE SCHEMA IF NOT EXISTS raw_kamis;
CREATE SCHEMA IF NOT EXISTS raw_knbs;
CREATE SCHEMA IF NOT EXISTS analytics;

-- 2. Raw Retail Tables (Synthetic POS & Inventory)
CREATE TABLE IF NOT EXISTS raw_retail.stores (
    store_id VARCHAR(10) PRIMARY KEY,
    store_name VARCHAR(100) NOT NULL,
    county VARCHAR(50) NOT NULL,
    opened_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_retail.suppliers (
    supplier_id VARCHAR(10) PRIMARY KEY,
    supplier_name VARCHAR(100) NOT NULL,
    county VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_retail.products (
    product_id VARCHAR(10) PRIMARY KEY,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    unit VARCHAR(20) NOT NULL,
    base_price NUMERIC(10, 2) NOT NULL,
    kamis_commodity VARCHAR(100) NOT NULL,
    supplier_id VARCHAR(10) REFERENCES raw_retail.suppliers(supplier_id)
);

CREATE TABLE IF NOT EXISTS raw_retail.pos_transactions (
    transaction_id VARCHAR(30) NOT NULL,
    line_no INT NOT NULL,
    store_id VARCHAR(10) NOT NULL,
    product_id VARCHAR(10) NOT NULL,
    quantity INT NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,
    line_total NUMERIC(10, 2) NOT NULL,
    payment_method VARCHAR(20) NOT NULL,
    sold_at TIMESTAMP NOT NULL,
    PRIMARY KEY (transaction_id, line_no)
);

CREATE TABLE IF NOT EXISTS raw_retail.inventory_movements (
    movement_id VARCHAR(30) PRIMARY KEY,
    store_id VARCHAR(10) NOT NULL,
    product_id VARCHAR(10) NOT NULL,
    movement_type VARCHAR(20) NOT NULL,
    quantity_change INT NOT NULL,
    supplier_id VARCHAR(10),
    moved_at TIMESTAMP NOT NULL
);

-- 3. Raw KAMIS Table (Ministry of Agriculture Market Prices)
CREATE TABLE IF NOT EXISTS raw_kamis.market_prices (
    commodity VARCHAR(100) NOT NULL,
    classification VARCHAR(50),
    grade VARCHAR(50),
    sex VARCHAR(50),
    market VARCHAR(100) NOT NULL,
    wholesale VARCHAR(50),
    retail VARCHAR(50),
    supply_volume VARCHAR(50),
    county VARCHAR(50) NOT NULL,
    price_date DATE NOT NULL,
    source_file VARCHAR(100),
    ingested_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kamis_date_county_commodity 
ON raw_kamis.market_prices (price_date, county, commodity);

-- 4. Raw KNBS Tables (Official Consumer Price Index & National Benchmarks)
CREATE TABLE IF NOT EXISTS raw_knbs.cpi_divisions (
    report_date DATE NOT NULL,
    division_name VARCHAR(150) NOT NULL,
    weight_pct NUMERIC(6, 4) NOT NULL,
    mom_change_pct NUMERIC(5, 2) NOT NULL,
    yoy_change_pct NUMERIC(5, 2) NOT NULL,
    PRIMARY KEY (report_date, division_name)
);

CREATE TABLE IF NOT EXISTS raw_knbs.cpi_monthly_trend (
    period VARCHAR(10) PRIMARY KEY,
    year_month VARCHAR(7) NOT NULL,
    overall_cpi NUMERIC(6, 2),
    overall_inflation_pct NUMERIC(5, 2),
    core_index NUMERIC(6, 2),
    core_inflation_pct NUMERIC(5, 2),
    non_core_index NUMERIC(6, 2),
    non_core_inflation_pct NUMERIC(5, 2)
);

CREATE TABLE IF NOT EXISTS raw_knbs.commodity_retail_prices (
    report_date DATE NOT NULL,
    commodity_name VARCHAR(150) NOT NULL,
    quantity INT NOT NULL,
    unit VARCHAR(50) NOT NULL,
    avg_price_sep_2025 NUMERIC(10, 2),
    avg_price_aug_2026 NUMERIC(10, 2),
    avg_price_sep_2026 NUMERIC(10, 2),
    mom_pct_change NUMERIC(5, 2),
    yoy_pct_change NUMERIC(5, 2),
    PRIMARY KEY (report_date, commodity_name)
);

CREATE TABLE IF NOT EXISTS raw_knbs.commodity_benchmarks (
    product_id VARCHAR(10) PRIMARY KEY,
    catalog_product_name VARCHAR(100) NOT NULL,
    kamis_commodity VARCHAR(100) NOT NULL,
    knbs_commodity_name VARCHAR(150) NOT NULL,
    knbs_quantity INT NOT NULL,
    knbs_unit VARCHAR(50) NOT NULL,
    knbs_price_sep_2025 NUMERIC(10, 2),
    knbs_price_aug_2026 NUMERIC(10, 2),
    knbs_price_sep_2026 NUMERIC(10, 2),
    knbs_mom_change_pct NUMERIC(5, 2),
    knbs_yoy_change_pct NUMERIC(5, 2)
);

-- 5. Analytics Mart Views

-- View: Daily Retail Sales vs County KAMIS Market Prices vs KNBS Benchmark
CREATE OR REPLACE VIEW analytics.v_price_benchmark_comparison AS
WITH daily_store_sales AS (
    SELECT 
        DATE(t.sold_at) AS sale_date,
        s.county,
        t.store_id,
        s.store_name,
        p.product_id,
        p.product_name,
        p.kamis_commodity,
        COUNT(DISTINCT t.transaction_id) AS tx_count,
        SUM(t.quantity) AS total_units_sold,
        ROUND(AVG(t.unit_price), 2) AS avg_retail_shelf_price,
        SUM(t.line_total) AS total_revenue
    FROM raw_retail.pos_transactions t
    JOIN raw_retail.stores s ON t.store_id = s.store_id
    JOIN raw_retail.products p ON t.product_id = p.product_id
    GROUP BY DATE(t.sold_at), s.county, t.store_id, s.store_name, p.product_id, p.product_name, p.kamis_commodity
),
daily_kamis_prices AS (
    SELECT 
        k.price_date,
        k.county,
        k.commodity,
        -- Extract numeric retail price from strings like '100.00/Kg'
        ROUND(AVG(NULLIF(REGEXP_REPLACE(k.retail, '[^0-9.]', '', 'g'), '')::NUMERIC), 2) AS avg_kamis_retail_price,
        ROUND(AVG(NULLIF(REGEXP_REPLACE(k.wholesale, '[^0-9.]', '', 'g'), '')::NUMERIC), 2) AS avg_kamis_wholesale_price
    FROM raw_kamis.market_prices k
    GROUP BY k.price_date, k.county, k.commodity
)
SELECT 
    d.sale_date,
    d.county,
    d.store_id,
    d.store_name,
    d.product_id,
    d.product_name,
    d.kamis_commodity,
    d.total_units_sold,
    d.total_revenue,
    d.avg_retail_shelf_price,
    kp.avg_kamis_wholesale_price,
    kp.avg_kamis_retail_price AS kamis_county_market_price,
    ROUND(d.avg_retail_shelf_price - kp.avg_kamis_retail_price, 2) AS diff_vs_kamis_market,
    kb.knbs_price_sep_2026 AS knbs_national_benchmark_price,
    ROUND(d.avg_retail_shelf_price - kb.knbs_price_sep_2026, 2) AS diff_vs_knbs_national
FROM daily_store_sales d
LEFT JOIN daily_kamis_prices kp 
    ON d.sale_date = kp.price_date 
   AND d.county = kp.county 
   AND d.kamis_commodity = kp.commodity
LEFT JOIN raw_knbs.commodity_benchmarks kb
    ON d.product_id = kb.product_id;

-- View: Inventory Wastage by Category and County
CREATE OR REPLACE VIEW analytics.v_inventory_shrinkage AS
SELECT 
    DATE(m.moved_at) AS movement_date,
    s.county,
    s.store_name,
    p.category,
    p.product_name,
    SUM(CASE WHEN m.movement_type = 'RESTOCK' THEN m.quantity_change ELSE 0 END) AS units_restocked,
    SUM(CASE WHEN m.movement_type = 'SALE' THEN ABS(m.quantity_change) ELSE 0 END) AS units_sold,
    SUM(CASE WHEN m.movement_type = 'WASTAGE' THEN ABS(m.quantity_change) ELSE 0 END) AS units_wasted,
    ROUND(
        SUM(CASE WHEN m.movement_type = 'WASTAGE' THEN ABS(m.quantity_change) ELSE 0 END)::NUMERIC * 100.0 / 
        NULLIF(SUM(CASE WHEN m.movement_type = 'SALE' THEN ABS(m.quantity_change) ELSE 0 END), 0),
        2
    ) AS wastage_pct_of_sales
FROM raw_retail.inventory_movements m
JOIN raw_retail.stores s ON m.store_id = s.store_id
JOIN raw_retail.products p ON m.product_id = p.product_id
GROUP BY DATE(m.moved_at), s.county, s.store_name, p.category, p.product_name;
