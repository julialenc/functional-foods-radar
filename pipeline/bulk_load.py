"""
bulk_load.py
------------
Reads the Open Food Facts bulk CSV export in chunks.
Filters to relevant categories, maps column names to match
the existing pipeline schema, then runs clean + analyze + load.

This script establishes the PRODUCTION BASELINE in SQLite.
After this runs, weekly API diffs (run.py) maintain the database.

Usage:
    python pipeline/bulk_load.py

Input:
    data/raw/off_full_export.csv.gz   (~9GB compressed, tab-separated)

Output:
    data/sample/bulk_clean_<timestamp>.csv
    data/sample/bulk_analyzed_<timestamp>.csv
    database/functional_food_radar.db  (production baseline)

See docs/ADR.md ADR-001 and docs/DATA_OBSERVATIONS.md OBS-012.
"""

import pandas as pd
import os
import sys
from datetime import datetime

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GZ_PATH    = os.path.join(ROOT, "data", "raw", "off_full_export.csv.gz")
SAMPLE_DIR = os.path.join(ROOT, "data", "sample")

# ── Category filter ───────────────────────────────────────────────────────────
# OFF bulk export uses categories_tags (pipe/comma separated, en: prefixed)
# We match any product whose categories_tags contains one of these strings

CATEGORY_KEYWORDS = [
    "en:snacks",
    "en:beverages",
    "en:breakfast-cereals",
    "en:cereals",
    "en:biscuits-and-cakes",
    "en:dairy-desserts",
    "en:plant-based-foods",
]

# ── Column mapping ─────────────────────────────────────────────────────────────
# Bulk export column -> pipeline column name
# 23/23 fields confirmed present by explore_export.py

COLUMN_MAP = {
    "code":                 "barcode",
    "product_name":         "product_name",
    "brands":               "brands",
    "categories":           "off_categories",
    "categories_tags":      "categories_tags",   # used for filtering, kept
    "ingredients_text":     "ingredients_text",
    "energy-kcal_100g":     "energy_kcal",
    "fat_100g":             "fat_100g",
    "saturated-fat_100g":   "saturated_fat_100g",
    "carbohydrates_100g":   "carbs_100g",
    "sugars_100g":          "sugars_100g",
    "fiber_100g":           "fiber_100g",
    "proteins_100g":        "protein_100g",
    "salt_100g":            "salt_100g",
    "nutriscore_grade":     "nutriscore_grade",
    "nova_group":           "nova_group",
    "countries_tags":       "countries",
    "labels_tags":          "labels",
    "quantity":             "quantity",
    "packaging":            "packaging",
    "created_t":            "created_t",
    "last_modified_t":      "last_modified_t",
    "additives_tags":       "additives_tags",
    "image_url":            "image_url",         # v3 — stored but not used yet
}

USECOLS = list(COLUMN_MAP.keys())

# ── Chunk settings ────────────────────────────────────────────────────────────
CHUNK_SIZE = 50_000   # rows per chunk — safe for 16GB RAM


def category_match(cat_str):
    """Return True if any category keyword matches the categories_tags field."""
    if not isinstance(cat_str, str):
        return False
    cat_lower = cat_str.lower()
    return any(kw in cat_lower for kw in CATEGORY_KEYWORDS)


def process_chunks():
    """
    Read bulk export in chunks, filter categories, return combined DataFrame.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\nFunctional Food Radar - bulk_load.py")
    print(f"Run timestamp: {timestamp}")
    print(f"Input: {GZ_PATH}")
    print(f"Category keywords: {CATEGORY_KEYWORDS}\n")

    chunks_processed = 0
    rows_read        = 0
    rows_kept        = 0
    all_filtered     = []

    reader = pd.read_csv(
        GZ_PATH,
        sep="\t",
        usecols=USECOLS,
        chunksize=CHUNK_SIZE,
        low_memory=False,
        on_bad_lines="skip",
        encoding="utf-8",
    )

    for chunk in reader:
        chunks_processed += 1
        rows_read += len(chunk)

        # Filter by category
        mask = chunk["categories_tags"].apply(category_match)
        filtered = chunk[mask].copy()

        # Filter out invalid image URLs (OBS-018)
        if "image_url" in filtered.columns:
            filtered = filtered[
                ~filtered["image_url"].str.contains("/invalid/", na=True)
            ]

        rows_kept += len(filtered)
        all_filtered.append(filtered)

        if chunks_processed % 10 == 0:
            print(f"  Chunk {chunks_processed:>4}: "
                  f"{rows_read:>8,} rows read, "
                  f"{rows_kept:>7,} kept "
                  f"({rows_kept/rows_read*100:.1f}%)")

    print(f"\n  Total chunks: {chunks_processed}")
    print(f"  Total rows read: {rows_read:,}")
    print(f"  Total rows kept: {rows_kept:,} ({rows_kept/rows_read*100:.1f}%)")

    if not all_filtered:
        print("ERROR: No rows matched category filter. Check CATEGORY_KEYWORDS.")
        sys.exit(1)

    df = pd.concat(all_filtered, ignore_index=True)

    # Rename columns to match pipeline schema
    df = df.rename(columns=COLUMN_MAP)

    # Add query_category from categories_tags (best match)
    def infer_category(cat_str):
        if not isinstance(cat_str, str):
            return "unknown"
        cat_lower = cat_str.lower()
        if "en:snacks" in cat_lower or "en:biscuits" in cat_lower:
            return "snacks"
        if "en:beverages" in cat_lower:
            return "beverages"
        if "en:cereals" in cat_lower or "en:breakfast-cereals" in cat_lower:
            return "cereals"
        if "en:dairy-desserts" in cat_lower:
            return "dairy-desserts"
        if "en:plant-based" in cat_lower:
            return "plant-based-foods"
        return "other"

    df["query_category"] = df["categories_tags"].apply(infer_category)

    # Drop the raw categories_tags — already captured in off_categories
    df = df.drop(columns=["categories_tags"], errors="ignore")

    print(f"\n  Query category distribution:")
    print("  " + df["query_category"].value_counts().to_string()
          .replace("\n", "\n  "))

    return df, timestamp


def main():
    # ── Step 1: Read and filter bulk export ───────────────────────────────────
    df_raw, timestamp = process_chunks()

    # ── Step 2: Save raw filtered CSV ────────────────────────────────────────
    raw_path = os.path.join(SAMPLE_DIR, f"bulk_raw_{timestamp}.csv")
    df_raw.to_csv(raw_path, index=False, encoding="utf-8-sig")
    print(f"\n  Raw filtered CSV saved -> bulk_raw_{timestamp}.csv")
    print(f"  ({len(df_raw):,} rows, {len(df_raw.columns)} columns)")

    # ── Step 3: Run clean pipeline ────────────────────────────────────────────
    print(f"\n  Running clean pipeline...")
    sys.path.insert(0, os.path.join(ROOT, "pipeline"))
    from clean import clean

    # Temporarily override the sample dir auto-detection
    # by passing path directly
    df_clean = clean(raw_path)

    clean_path = os.path.join(SAMPLE_DIR, f"bulk_clean_{timestamp}.csv")
    df_clean.to_csv(clean_path, index=False, encoding="utf-8-sig")
    print(f"\n  Clean CSV saved -> bulk_clean_{timestamp}.csv")
    print(f"  ({len(df_clean):,} rows)")

    # ── Step 4: Run analyze pipeline ─────────────────────────────────────────
    print(f"\n  Running analyze pipeline...")
    from analyze import analyze

    df_analyzed = analyze(clean_path)

    analyzed_path = os.path.join(SAMPLE_DIR, f"bulk_analyzed_{timestamp}.csv")
    df_analyzed.to_csv(analyzed_path, index=False, encoding="utf-8-sig")
    print(f"\n  Analyzed CSV saved -> bulk_analyzed_{timestamp}.csv")
    print(f"  ({len(df_analyzed):,} rows)")

    # ── Step 5: Run load pipeline ─────────────────────────────────────────────
    print(f"\n  Running load pipeline...")
    from load import main as load_main

    # load.py auto-detects latest analyzed_*.csv — rename to trigger it
    # Actually bulk_analyzed won't be auto-detected so we call load directly
    import sqlite3
    from load import (init_db, load_products, load_nlp_results,
                      compute_weekly_brand_summary, export_powerbi_csvs,
                      log_run, DB_PATH)

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        init_db(conn)
        p_ins, p_upd = load_products(df_analyzed, conn, timestamp)
        print(f"  Products: {p_ins:,} inserted, {p_upd:,} updated")

        n_ins, n_upd = load_nlp_results(df_analyzed, conn, timestamp)
        print(f"  NLP results: {n_ins:,} inserted, {n_upd:,} updated")

        compute_weekly_brand_summary(df_analyzed, conn, timestamp)
        export_powerbi_csvs(df_analyzed, timestamp)

        log_run(conn, timestamp, analyzed_path, len(df_analyzed),
                p_ins, p_upd, n_ins, n_upd, "success",
                "bulk_export_load")

        # Summary
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM products")
        total = cursor.fetchone()[0]
        print(f"\n  Total products in DB: {total:,}")

        cursor.execute("""
            SELECT health_wash_category, COUNT(*) as cnt
            FROM nlp_results
            WHERE health_wash_category IS NOT NULL
            GROUP BY health_wash_category
            ORDER BY cnt DESC
        """)
        print(f"\n  Health-wash distribution:")
        for cat, cnt in cursor.fetchall():
            print(f"    {cat:<45} {cnt:,}")

    except Exception as e:
        log_run(conn, timestamp, analyzed_path, len(df_analyzed),
                0, 0, 0, 0, "failed", str(e))
        raise
    finally:
        conn.close()

    print(f"\n  Production baseline complete.")
    print(f"  Database: {DB_PATH}")
    print(f"  Weekly API diff (run.py) will maintain from here.\n")


if __name__ == "__main__":
    main()