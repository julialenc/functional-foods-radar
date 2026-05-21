"""
explore_export.py
-----------------
Peeks at the OFF bulk CSV export before running the full pipeline.
Checks column names, sample rows, and key field availability.

Usage:
    python pipeline/explore_export.py

Input:
    data/raw/off_full_export.csv.gz
"""

import pandas as pd
import os

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GZ_PATH  = os.path.join(ROOT, "data", "raw", "off_full_export.csv.gz")

# Columns we need from the API — check if they exist in bulk export
API_FIELDS = [
    "code",
    "product_name",
    "brands",
    "categories",
    "ingredients_text",
    "energy-kcal_100g",      # nutriments are flat in bulk export
    "fat_100g",
    "saturated-fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "nutriscore_grade",
    "nova_group",
    "countries_tags",
    "labels_tags",
    "quantity",
    "packaging",
    "created_t",
    "last_modified_t",
    "additives_tags",
    "image_url",             # available in bulk export for v3
]


def explore():
    print(f"\nFunctional Food Radar - explore_export.py")
    print(f"Reading first 5 rows from bulk export...\n")

    # Read just the first 5 rows — fast
    df = pd.read_csv(
        GZ_PATH,
        nrows=5,
        sep="\t",            # OFF bulk export is TAB separated
        low_memory=False,
        on_bad_lines="skip",
    )

    print(f"Total columns in bulk export: {len(df.columns)}")
    print(f"\nAll column names:")
    for i, col in enumerate(df.columns):
        print(f"  {i:>3}. {col}")

    print(f"\n--- Checking our required API fields ---")
    missing = []
    found   = []
    for field in API_FIELDS:
        if field in df.columns:
            found.append(field)
            print(f"  OK      {field}")
        else:
            missing.append(field)
            print(f"  MISSING {field}")

    print(f"\nFound:   {len(found)}/{len(API_FIELDS)}")
    print(f"Missing: {len(missing)}/{len(API_FIELDS)}")

    if missing:
        print(f"\nMissing fields — may need column name mapping:")
        for f in missing:
            # Show similar column names
            similar = [c for c in df.columns if any(
                part in c.lower() for part in f.lower().split("-")
            )][:3]
            print(f"  {f} -> possible matches: {similar}")

    print(f"\n--- Sample row (first product) ---")
    if len(df) > 0:
        row = df.iloc[0]
        for field in API_FIELDS:
            if field in df.columns:
                val = str(row[field])[:80]
                print(f"  {field:<30} {val}")

    # Check how many products are in each category
    print(f"\n--- Reading 1000 rows to check category distribution ---")
    df1k = pd.read_csv(
        GZ_PATH,
        nrows=1000,
        sep="\t",
        low_memory=False,
        on_bad_lines="skip",
        usecols=lambda c: c in ["categories_tags", "categories"],
    )
    cat_col = "categories_tags" if "categories_tags" in df1k.columns else "categories"
    print(f"  Category column used: {cat_col}")
    print(f"  Sample values:")
    print(df1k[cat_col].dropna().head(5).to_string())


if __name__ == "__main__":
    explore()