"""
ingest.py
---------
Pulls products from the Open Food Facts Live JSON API by category.
Saves raw JSON to data/raw/ and a flat CSV to data/sample/.

Usage:
    python pipeline/ingest.py

Output:
    data/raw/raw_<category>_<timestamp>.json   (one per category)
    data/sample/sample_all_<timestamp>.csv     (all categories combined, flat)
"""

import requests
import pandas as pd
import json
import os
from datetime import datetime

# ── Configuration ────────────────────────────────────────────────────────────

USER_AGENT = "FunctionalFoodRadar/1.0 (student project; github.com/julialenc/functional-foods-radar)"

CATEGORIES = [
    "snacks",
    "beverages",
    "cereals",
]

PRODUCTS_PER_CATEGORY = 150  # increase later for production runs

BASE_URL = "https://world.openfoodfacts.org/cgi/search.pl"

# Fields we actually need — keeps response light
FIELDS = ",".join([
    "code",
    "product_name",
    "brands",
    "categories",
    "ingredients_text",
    "nutriments",
    "nutriscore_grade",
    "nova_group",
    "countries_tags",
    "labels_tags",
    "quantity",
    "packaging",
    "created_t",
    "last_modified_t",
    "additives_tags",       # E-number list pre-parsed by OFF — used in analyze.py Option A
    # "image_url",          # v3: front-of-pack image for LLM claim extraction
                            # Excluded from v1 — tens of thousands of products,
                            # images not needed until claim-vs-reality gap analysis.
                            # Uncomment when ready for v3 vision pipeline.
                            # Use open source vision model (LLaVA/InternVL2), not
                            # Azure/OpenAI — cost prohibitive at this scale.
])

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR    = os.path.join(ROOT, "data", "raw")
SAMPLE_DIR = os.path.join(ROOT, "data", "sample")

# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_category(category: str, n: int = PRODUCTS_PER_CATEGORY) -> list[dict]:
    """
    Fetch n products for a given OFF category.
    Returns a list of product dicts.
    """
    params = {
        "action":           "process",
        "tagtype_0":        "categories",
        "tag_contains_0":   "contains",
        "tag_0":            category,
        "fields":           FIELDS,
        "page_size":        n,
        "page":             1,
        "json":             1,
    }

    headers = {"User-Agent": USER_AGENT}
    import time

    print(f"  Fetching '{category}' ({n} products)...")
    for attempt in range(3):
        response = requests.get(BASE_URL, params=params, headers=headers, timeout=30)
        if response.status_code == 503:
            wait = 10 * (attempt + 1)
            print(f"  503 received, retrying in {wait}s (attempt {attempt + 1}/3)...")
            time.sleep(wait)
            continue
        response.raise_for_status()
        break

    data = response.json()
    products = data.get("products", [])
    print(f"  → {len(products)} products received")
    return products


# ── Flatten ───────────────────────────────────────────────────────────────────

def flatten_product(product: dict, category: str) -> dict:
    """
    Flatten a single product dict into a row suitable for a DataFrame.
    Nutriments are a nested dict — we extract the key macros only.
    """
    nutriments = product.get("nutriments", {})

    return {
        # identifiers
        "barcode":              product.get("code", ""),
        "product_name":         product.get("product_name", ""),
        "brands":               product.get("brands", ""),
        "quantity":             product.get("quantity", ""),
        "packaging":            product.get("packaging", ""),

        # categorisation
        "query_category":       category,
        "off_categories":       product.get("categories", ""),
        "countries":            "|".join(product.get("countries_tags", [])),
        "labels":               "|".join(product.get("labels_tags", [])),

        # ingredients (raw text — clean.py will parse this)
        "ingredients_text":     product.get("ingredients_text", ""),

        # nutrition (per 100g)
        "energy_kcal":          nutriments.get("energy-kcal_100g", None),
        "fat_100g":             nutriments.get("fat_100g", None),
        "saturated_fat_100g":   nutriments.get("saturated-fat_100g", None),
        "carbs_100g":           nutriments.get("carbohydrates_100g", None),
        "sugars_100g":          nutriments.get("sugars_100g", None),
        "fiber_100g":           nutriments.get("fiber_100g", None),
        "protein_100g":         nutriments.get("proteins_100g", None),
        "salt_100g":            nutriments.get("salt_100g", None),

        # scores (pre-computed by OFF — useful as ground truth for v2)
        "nutriscore_grade":     product.get("nutriscore_grade", ""),
        "nova_group":           product.get("nova_group", None),

        # timestamps
        "created_t":            product.get("created_t", None),
        "last_modified_t":      product.get("last_modified_t", None),
    }


# ── Save ──────────────────────────────────────────────────────────────────────

def save_raw(products: list[dict], category: str, timestamp: str) -> None:
    """Save raw API response to data/raw/ as JSON."""
    filename = f"raw_{category}_{timestamp}.json"
    path = os.path.join(RAW_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    print(f"  Raw JSON saved → {filename}")


def save_sample(df: pd.DataFrame, timestamp: str) -> None:
    """Save combined flat CSV to data/sample/."""
    filename = f"sample_all_{timestamp}.csv"
    path = os.path.join(SAMPLE_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # utf-8-sig for Excel compatibility
    print(f"  Sample CSV saved → {filename}  ({len(df)} rows, {len(df.columns)} columns)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\nFunctional Food Radar — ingest.py")
    print(f"Run timestamp: {timestamp}")
    print(f"Categories: {CATEGORIES}")
    print(f"Products per category: {PRODUCTS_PER_CATEGORY}\n")

    all_rows = []

    for i, category in enumerate(CATEGORIES):
        if i > 0:
            print("  Pausing 5s between categories...")
            import time; time.sleep(5)
        products = fetch_category(category)
        save_raw(products, category, timestamp)

        rows = [flatten_product(p, category) for p in products]
        all_rows.extend(rows)
        print()

    df = pd.DataFrame(all_rows)
    save_sample(df, timestamp)

    print(f"\nDone. {len(df)} total products across {len(CATEGORIES)} categories.")
    print(f"Nulls per column:\n{df.isnull().sum().to_string()}\n")


if __name__ == "__main__":
    main()
