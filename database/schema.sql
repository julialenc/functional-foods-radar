CREATE INDEX idx_nlp_category ON nlp_results(health_wash_category);

CREATE INDEX idx_nlp_score ON nlp_results(health_wash_score);

CREATE INDEX idx_products_brand ON products(brands);

CREATE INDEX idx_products_category ON products(query_category);

CREATE INDEX idx_products_country ON products(primary_country);

CREATE INDEX idx_products_modified ON products(last_modified_t);

CREATE INDEX idx_products_nova ON products(nova_group);

CREATE TABLE ingestion_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp     TEXT,
    source            TEXT,    -- 'api' or 'bulk_export'
    input_file        TEXT,
    category          TEXT,    -- 'all' or specific category
    rows_in_file      INTEGER,
    products_inserted INTEGER,
    products_updated  INTEGER,
    nlp_inserted      INTEGER,
    nlp_updated       INTEGER,
    status            TEXT,    -- 'success' / 'partial' / 'failed'
    notes             TEXT
);

CREATE TABLE nlp_results (
    barcode                    TEXT PRIMARY KEY,
    upf_marker_count           INTEGER,
    upf_markers_found          TEXT,
    upf_max_severity           INTEGER,
    has_ultra_processed        INTEGER,   -- 1/0 boolean
    e_number_count             INTEGER,
    e_numbers_found            TEXT,
    has_artificial_sweetener   INTEGER,   -- 1/0 boolean
    functional_claim_count     INTEGER,
    functional_claims_found    TEXT,
    negative_claim_count       INTEGER,
    negative_claims_found      TEXT,
    health_wash_score          REAL,
    health_wash_category       TEXT,
    cluster_label              TEXT,      -- null in v1, populated in v2
    analyzed_at                TEXT,      -- when this row was analyzed
    FOREIGN KEY (barcode) REFERENCES products(barcode)
);

CREATE TABLE products (
    barcode                TEXT PRIMARY KEY,
    product_name           TEXT,
    brands                 TEXT,
    primary_brand          TEXT,
    quantity               TEXT,
    packaging              TEXT,
    query_category         TEXT,
    off_categories         TEXT,
    countries              TEXT,
    primary_country        TEXT,
    labels                 TEXT,
    ingredients_text       TEXT,
    additives_tags         TEXT,
    energy_kcal            REAL,
    fat_100g               REAL,
    saturated_fat_100g     REAL,
    carbs_100g             REAL,
    sugars_100g            REAL,
    fiber_100g             REAL,
    protein_100g           REAL,
    salt_100g              REAL,
    nutriscore_grade       TEXT,
    nova_group             REAL,
    completeness_score     INTEGER,
    ingredients_lang       TEXT,
    nlp_eligible           INTEGER,   -- 1/0 boolean
    created_t              TEXT,
    last_modified_t        TEXT,
    ingested_at            TEXT       -- when this row was loaded by us
);

CREATE TABLE sqlite_sequence(name,seq);

CREATE TABLE weekly_brand_summary (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    week_ending                TEXT,      -- ISO date of week end
    brands                     TEXT,
    query_category             TEXT,
    product_count              INTEGER,
    avg_health_wash_score      REAL,
    high_score_count           INTEGER,   -- score >= 70
    medium_score_count         INTEGER,   -- score 45-69
    pct_nova4                  REAL,
    pct_with_functional_claims REAL,
    pct_with_artificial_sweet  REAL,
    top_claim_type             TEXT,
    run_timestamp              TEXT
);

