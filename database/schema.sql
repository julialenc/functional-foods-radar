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
    health_wash_score_v1       REAL,
    health_wash_category_v1    TEXT,
    cluster_label              TEXT,      -- null in v1, populated in v2
    analyzed_at                TEXT,      -- when this row was analyzed
    health_wash_score_v3       REAL,      -- populated by merge_scores.py
    health_wash_category_v3    TEXT,
    v3_claims_found            TEXT,
    ht_sugar_loophole          INTEGER,   -- 1/0 half-truth pattern flags
    ht_protein_masks_fat       INTEGER,
    ht_fibre_distraction       INTEGER,
    ht_vegan_calorie_trap      INTEGER,
    v3_immune_claim            INTEGER,
    v3_gender_targeting_claim  INTEGER,
    v3_vegan_claim             INTEGER,
    v3_organic_claim           INTEGER,
    v3_dairy_free_claim        INTEGER,
    v3_plant_based_claim       INTEGER,
    v3_heritage_claim          INTEGER,
    v3_gluten_free_claim       INTEGER,
    v3_minimal_ingredients_claim INTEGER,
    v3_no_palm_oil_claim       INTEGER,
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
    ingested_at            TEXT,      -- when this row was loaded by us
    image_url              TEXT       -- front-of-pack image URL for v3 vision
);

CREATE TABLE sqlite_sequence(name,seq);

CREATE TABLE weekly_brand_summary (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    week_ending                TEXT,      -- ISO date of week end
    brands                     TEXT,
    query_category             TEXT,
    product_count              INTEGER,
    avg_health_wash_score_v1   REAL,
    high_score_count           INTEGER,   -- score >= 70
    medium_score_count         INTEGER,   -- score 45-69
    pct_nova4                  REAL,
    pct_with_functional_claims REAL,
    pct_with_artificial_sweet  REAL,
    top_claim_type             TEXT,
    run_timestamp              TEXT
);

