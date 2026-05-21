"""
load.py
-------
Loads analyzed product data into SQLite database.
Also writes a clean CSV for future Power BI connection.

Schema:
    products             — product identity + nutrition (UPSERT on barcode)
    nlp_results          — NLP scores + flags (UPSERT on barcode)
    weekly_brand_summary — pre-aggregated for Power BI trend charts
    ingestion_log        — one row per pipeline run

Design principles:
    - INSERT OR REPLACE on barcode — idempotent, safe to run multiple times
    - last_modified_t drives weekly diff logic in production
    - weekly_brand_summary pre-aggregated so Power BI never touches raw rows
    - ingestion_log records source (api / bulk_export) for auditability

Usage:
    python pipeline/load.py

Input:
    data/sample/analyzed_<timestamp>.csv   (latest file auto-detected)

Output:
    database/functional_food_radar.db
    data/sample/powerbi_products_<timestamp>.csv
    data/sample/powerbi_nlp_<timestamp>.csv

Production note:
    Week 0: run on full OFF bulk export (~50,000-100,000 filtered products)
    Weekly: run on API diff (last_modified_t > 7 days) — same script,
    different input size. See docs/ADR.md and docs/DATA_OBSERVATIONS.md
    OBS-012 for full production strategy.
"""

import pandas as pd
import sqlite3
import os
from datetime import datetime


# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(ROOT, "data", "sample")
DB_DIR     = os.path.join(ROOT, "database")
DB_PATH    = os.path.join(DB_DIR, "functional_food_radar.db")


# ── Schema ────────────────────────────────────────────────────────────────────

DDL_PRODUCTS = """
CREATE TABLE IF NOT EXISTS products (
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
"""

DDL_NLP_RESULTS = """
CREATE TABLE IF NOT EXISTS nlp_results (
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
"""

DDL_WEEKLY_BRAND_SUMMARY = """
CREATE TABLE IF NOT EXISTS weekly_brand_summary (
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
"""

DDL_INGESTION_LOG = """
CREATE TABLE IF NOT EXISTS ingestion_log (
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
"""

DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brands);",
    "CREATE INDEX IF NOT EXISTS idx_products_category ON products(query_category);",
    "CREATE INDEX IF NOT EXISTS idx_products_country ON products(primary_country);",
    "CREATE INDEX IF NOT EXISTS idx_products_nova ON products(nova_group);",
    "CREATE INDEX IF NOT EXISTS idx_products_modified ON products(last_modified_t);",
    "CREATE INDEX IF NOT EXISTS idx_nlp_score ON nlp_results(health_wash_score);",
    "CREATE INDEX IF NOT EXISTS idx_nlp_category ON nlp_results(health_wash_category);",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_latest_analyzed(sample_dir):
    """Auto-detect the most recently created analyzed_*.csv file."""
    files = [
        f for f in os.listdir(sample_dir)
        if f.startswith("analyzed_") and f.endswith(".csv")
    ]
    if not files:
        raise FileNotFoundError(
            f"No analyzed_*.csv found in {sample_dir}. "
            "Run analyze.py first."
        )
    files.sort(reverse=True)
    return os.path.join(sample_dir, files[0])


def init_db(conn):
    """Create tables and indexes if they don't exist."""
    cursor = conn.cursor()
    cursor.execute(DDL_PRODUCTS)
    cursor.execute(DDL_NLP_RESULTS)
    cursor.execute(DDL_WEEKLY_BRAND_SUMMARY)
    cursor.execute(DDL_INGESTION_LOG)
    for idx_sql in DDL_INDEXES:
        cursor.execute(idx_sql)
    conn.commit()
    print(f"  Database initialised: {DB_PATH}")


def safe_val(val):
    """
    Convert pandas NA/NaN/None to Python None for SQLite insertion.
    Converts booleans to 1/0 for SQLite INTEGER storage.
    """
    if pd.isna(val) if not isinstance(val, (list, dict)) else False:
        return None
    if isinstance(val, bool):
        return 1 if val else 0
    if hasattr(val, 'item'):
        val = val.item()
    # Convert large integers to string to avoid SQLite overflow
    if isinstance(val, int) and (val > 2**63 - 1 or val < -(2**63)):
        return str(val)
    return val


# ── Products table ────────────────────────────────────────────────────────────

PRODUCT_COLS = [
    "barcode", "product_name", "brands", "primary_brand", "quantity", "packaging",
    "query_category", "off_categories", "countries", "primary_country",
    "labels", "ingredients_text", "additives_tags",
    "energy_kcal", "fat_100g", "saturated_fat_100g", "carbs_100g",
    "sugars_100g", "fiber_100g", "protein_100g", "salt_100g",
    "nutriscore_grade", "nova_group", "completeness_score",
    "ingredients_lang", "nlp_eligible", "created_t", "last_modified_t",
]

def load_products(df, conn, timestamp):
    """
    UPSERT products into the products table.
    Returns (inserted, updated) counts.
    """
    cursor   = conn.cursor()
    inserted = 0
    updated  = 0

    for _, row in df.iterrows():
        # Check if barcode exists
        cursor.execute(
            "SELECT barcode FROM products WHERE barcode = ?",
            (str(row["barcode"]),)
        )
        exists = cursor.fetchone() is not None

        values = [safe_val(row.get(col)) for col in PRODUCT_COLS]
        values.append(timestamp)   # ingested_at

        if exists:
            # UPDATE existing row
            set_clause = ", ".join(
                f"{col} = ?" for col in PRODUCT_COLS
            ) + ", ingested_at = ?"
            cursor.execute(
                f"UPDATE products SET {set_clause} WHERE barcode = ?",
                values + [str(row["barcode"])]
            )
            updated += 1
        else:
            # INSERT new row
            cols_str = ", ".join(PRODUCT_COLS) + ", ingested_at"
            placeholders = ", ".join("?" * (len(PRODUCT_COLS) + 1))
            cursor.execute(
                f"INSERT INTO products ({cols_str}) VALUES ({placeholders})",
                values
            )
            inserted += 1

    conn.commit()
    return inserted, updated


# ── NLP results table ─────────────────────────────────────────────────────────

NLP_COLS = [
    "barcode",
    "upf_marker_count", "upf_markers_found", "upf_max_severity",
    "has_ultra_processed", "e_number_count", "e_numbers_found",
    "has_artificial_sweetener", "functional_claim_count",
    "functional_claims_found", "negative_claim_count",
    "negative_claims_found", "health_wash_score",
    "health_wash_category", "cluster_label",
]

def load_nlp_results(df, conn, timestamp):
    """
    UPSERT NLP results into the nlp_results table.
    Only loads rows where nlp_eligible == True OR where
    health_wash_score is not null (some ineligible rows
    may have partial scores).
    Returns (inserted, updated) counts.
    """
    cursor   = conn.cursor()
    inserted = 0
    updated  = 0

    # Load all rows — ineligible rows get null NLP columns
    for _, row in df.iterrows():
        cursor.execute(
            "SELECT barcode FROM nlp_results WHERE barcode = ?",
            (str(row["barcode"]),)
        )
        exists = cursor.fetchone() is not None

        values = [safe_val(row.get(col)) for col in NLP_COLS]
        values.append(timestamp)   # analyzed_at

        if exists:
            set_clause = ", ".join(
                f"{col} = ?" for col in NLP_COLS
            ) + ", analyzed_at = ?"
            cursor.execute(
                f"UPDATE nlp_results SET {set_clause} WHERE barcode = ?",
                values + [str(row["barcode"])]
            )
            updated += 1
        else:
            cols_str = ", ".join(NLP_COLS) + ", analyzed_at"
            placeholders = ", ".join("?" * (len(NLP_COLS) + 1))
            cursor.execute(
                f"INSERT INTO nlp_results ({cols_str}) VALUES ({placeholders})",
                values
            )
            inserted += 1

    conn.commit()
    return inserted, updated


# ── Weekly brand summary ──────────────────────────────────────────────────────

def compute_weekly_brand_summary(df, conn, timestamp):
    """
    Compute brand-level aggregations and insert into weekly_brand_summary.
    This pre-aggregation means Power BI never touches raw product rows
    for trend charts.
    """
    cursor = conn.cursor()

    # Only use NLP-eligible rows with scores
    eligible = df[df["nlp_eligible"] == True].copy()
    eligible["health_wash_score"] = pd.to_numeric(
        eligible["health_wash_score"], errors="coerce"
    )
    eligible["nova_group"] = pd.to_numeric(
        eligible["nova_group"], errors="coerce"
    )

    # Week ending = today
    week_ending = datetime.now().strftime("%Y-%m-%d")

    # Group by brand + category
    grouped = eligible.groupby(["brands", "query_category"])

    rows_inserted = 0
    for (brand, category), group in grouped:
        if len(group) == 0:
            continue

        product_count    = len(group)
        avg_score        = group["health_wash_score"].mean()
        high_count       = (group["health_wash_score"] >= 70).sum()
        medium_count     = (
            (group["health_wash_score"] >= 45) &
            (group["health_wash_score"] < 70)
        ).sum()
        pct_nova4        = (
            (group["nova_group"] == 4.0).sum() / product_count * 100
        )
        pct_claims       = (
            (group["functional_claim_count"].fillna(0) > 0).sum() /
            product_count * 100
        )
        pct_sweetener    = (
            group["has_artificial_sweetener"]
            .apply(lambda x: 1 if x == True or x == 1 else 0)
            .sum() / product_count * 100
        )

        # Top claim type for this brand/category
        all_claims = []
        for claims in group["functional_claims_found"].dropna():
            all_claims.extend(str(claims).split("|"))
        top_claim = (
            max(set(all_claims), key=all_claims.count)
            if all_claims else None
        )

        cursor.execute("""
            INSERT INTO weekly_brand_summary (
                week_ending, brands, query_category,
                product_count, avg_health_wash_score,
                high_score_count, medium_score_count,
                pct_nova4, pct_with_functional_claims,
                pct_with_artificial_sweet, top_claim_type,
                run_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            week_ending, brand, category,
            int(product_count), round(float(avg_score), 1) if pd.notna(avg_score) else None,
            int(high_count), int(medium_count),
            round(float(pct_nova4), 1),
            round(float(pct_claims), 1),
            round(float(pct_sweetener), 1),
            top_claim, timestamp
        ))
        rows_inserted += 1

    conn.commit()
    print(f"  Weekly brand summary: {rows_inserted} brand/category rows inserted")


# ── Power BI CSV export ───────────────────────────────────────────────────────

def export_powerbi_csvs(df, timestamp):
    """
    Write two clean CSVs for Power BI connection:
    - powerbi_products_<timestamp>.csv  — products + nutrition
    - powerbi_nlp_<timestamp>.csv       — NLP scores + flags

    These are flat, clean, Power BI-ready. No processing needed in DAX.
    utf-8-sig encoding for Excel/Power BI Windows compatibility.
    """
    # Products CSV
    product_cols_csv = PRODUCT_COLS + ["primary_country"]
    product_cols_csv = [c for c in product_cols_csv if c in df.columns]
    df_products = df[product_cols_csv].copy()
    products_path = os.path.join(
        SAMPLE_DIR, f"powerbi_products_{timestamp}.csv"
    )
    df_products.to_csv(products_path, index=False, encoding="utf-8-sig")
    print(f"  Power BI products CSV → powerbi_products_{timestamp}.csv "
          f"({len(df_products)} rows)")

    # NLP CSV
    nlp_cols_csv = [c for c in NLP_COLS if c in df.columns] + \
                   ["health_wash_category"]
    nlp_cols_csv = [c for c in nlp_cols_csv if c in df.columns]
    df_nlp = df[nlp_cols_csv].copy()
    nlp_path = os.path.join(
        SAMPLE_DIR, f"powerbi_nlp_{timestamp}.csv"
    )
    df_nlp.to_csv(nlp_path, index=False, encoding="utf-8-sig")
    print(f"  Power BI NLP CSV     → powerbi_nlp_{timestamp}.csv "
          f"({len(df_nlp)} rows)")


# ── Ingestion log ─────────────────────────────────────────────────────────────

def log_run(conn, timestamp, input_file, rows_in,
            p_ins, p_upd, n_ins, n_upd, status, notes=""):
    """Write a run record to ingestion_log."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ingestion_log (
            run_timestamp, source, input_file, category,
            rows_in_file, products_inserted, products_updated,
            nlp_inserted, nlp_updated, status, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        timestamp, "api", os.path.basename(input_file), "all",
        rows_in, p_ins, p_upd, n_ins, n_upd, status, notes
    ))
    conn.commit()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\nFunctional Food Radar — load.py")
    print(f"Run timestamp: {timestamp}")

    # ── Load analyzed CSV ─────────────────────────────────────────────────────
    input_path = find_latest_analyzed(SAMPLE_DIR)
    print(f"\n  Input file: {os.path.basename(input_path)}")
    df = pd.read_csv(input_path, encoding="utf-8-sig")
    print(f"  Rows: {len(df)}")

    # ── Connect to SQLite ─────────────────────────────────────────────────────
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")   # safer concurrent writes
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        # ── Initialise schema ─────────────────────────────────────────────────
        init_db(conn)

        # ── Load products ─────────────────────────────────────────────────────
        print(f"\n  Loading products table...")
        p_ins, p_upd = load_products(df, conn, timestamp)
        print(f"  Products: {p_ins} inserted, {p_upd} updated")

        # ── Load NLP results ──────────────────────────────────────────────────
        print(f"\n  Loading nlp_results table...")
        n_ins, n_upd = load_nlp_results(df, conn, timestamp)
        print(f"  NLP results: {n_ins} inserted, {n_upd} updated")

        # ── Compute weekly brand summary ──────────────────────────────────────
        print(f"\n  Computing weekly brand summary...")
        compute_weekly_brand_summary(df, conn, timestamp)

        # ── Export Power BI CSVs ──────────────────────────────────────────────
        print(f"\n  Exporting Power BI CSVs...")
        export_powerbi_csvs(df, timestamp)

        # ── Log the run ───────────────────────────────────────────────────────
        log_run(
            conn, timestamp, input_path, len(df),
            p_ins, p_upd, n_ins, n_upd, "success"
        )

        # ── Summary ───────────────────────────────────────────────────────────
        print(f"\n  -- Summary --------------------------------------------------")
        print(f"  Database: {DB_PATH}")

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM products")
        total_products = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM nlp_results WHERE health_wash_score IS NOT NULL")
        total_analyzed = cursor.fetchone()[0]

        cursor.execute("""
            SELECT health_wash_category, COUNT(*) as cnt
            FROM nlp_results
            WHERE health_wash_category IS NOT NULL
            GROUP BY health_wash_category
            ORDER BY cnt DESC
        """)
        categories = cursor.fetchall()

        cursor.execute("""
            SELECT primary_brand, AVG(health_wash_score) as avg_score, COUNT(*) as cnt
            FROM products p
            JOIN nlp_results n ON p.barcode = n.barcode
            WHERE n.health_wash_score IS NOT NULL
            GROUP BY primary_brand
            HAVING cnt >= 3
            ORDER BY avg_score DESC
            LIMIT 15
        """)
        top_brands = cursor.fetchall()

        print(f"  Total products in DB:  {total_products}")
        print(f"  Total NLP analyzed:    {total_analyzed}")
        print(f"\n  Health-wash distribution:")
        for cat, cnt in categories:
            print(f"    {cat:<45} {cnt}")
        print(f"\n  Top 10 brands by avg health-wash score (min 3 products):")
        for brand, avg, cnt in top_brands:
            print(f"    {str(brand):<35} avg={avg:.1f}  n={cnt}")

        cursor.execute("SELECT * FROM ingestion_log ORDER BY id DESC LIMIT 3")
        logs = cursor.fetchall()
        print(f"\n  Recent ingestion log:")
        for log in logs:
            print(f"    {log}")

    except Exception as e:
        log_run(
            conn, timestamp, input_path, len(df),
            0, 0, 0, 0, "failed", str(e)
        )
        raise

    finally:
        conn.close()

    print(f"\n  Done.\n")


if __name__ == "__main__":
    main()
