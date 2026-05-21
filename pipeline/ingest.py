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

PRODUCTS_PER_CATEGORY = 3000  # increase later for production runs

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

PAGE_SIZE = 100          # OFF API hard cap per page
PAGE_DELAY = 8           # seconds between pages — polite to OFF servers
MAX_RETRIES = 3          # attempts per page before giving up


def fetch_page(category: str, page: int, headers: dict) -> list[dict]:
    """
    Fetch a single page of products for a category.
    Returns list of product dicts, or empty list on failure.
    """
    import time

    params = {
        "action":           "process",
        "tagtype_0":        "categories",
        "tag_contains_0":   "contains",
        "tag_0":            category,
        "fields":           FIELDS,
        "page_size":        PAGE_SIZE,
        "page":             page,
        "json":             1,
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                BASE_URL, params=params,
                headers=headers, timeout=30
            )
            if response.status_code == 503:
                wait = 30 * (attempt + 1)
                print(f"    503 on page {page}, "
                      f"retrying in {wait}s "
                      f"(attempt {attempt + 1}/{MAX_RETRIES})...")
                time.sleep(wait)
                continue

            response.raise_for_status()

            if not response.text.strip():
                print(f"    Empty response on page {page}, skipping")
                return []

            data = response.json()
            return data.get("products", [])

        except Exception as e:
            print(f"    Error on page {page} attempt {attempt + 1}: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(20)

    print(f"    Giving up on page {page} after {MAX_RETRIES} attempts")
    return []


def fetch_category(category: str,
                   target: int = PRODUCTS_PER_CATEGORY) -> list[dict]:
    """
    Fetch up to `target` products for a category using pagination.
    Requests pages sequentially until target is reached or
    OFF returns no more products.
    Returns deduplicated list of product dicts.
    """
    import time

    headers  = {"User-Agent": USER_AGENT}
    all_products = []
    seen_codes   = set()
    page         = 1

    print(f"  Fetching '{category}' (target: {target} products, "
          f"{PAGE_SIZE}/page)...")

    while len(all_products) < target:
        page_products = fetch_page(category, page, headers)

        if not page_products:
            print(f"    No products on page {page} — "
                  f"category exhausted or server error")
            break

        # Deduplicate within this category fetch
        new = [p for p in page_products
               if p.get("code") not in seen_codes]
        for p in new:
            seen_codes.add(p.get("code"))
        all_products.extend(new)

        print(f"    Page {page}: {len(new)} new products "
              f"(total so far: {len(all_products)})")

        # Stop if OFF returned fewer than PAGE_SIZE — means no more pages
        if len(page_products) < PAGE_SIZE:
            print(f"    Reached end of category at page {page}")
            break

        page += 1

        # Polite delay between pages
        if len(all_products) < target:
            time.sleep(PAGE_DELAY)

    print(f"  -> {len(all_products)} total products for '{category}'")
    return all_products[:target]


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

        # additives (pre-parsed E-number list from OFF)
        # stored as pipe-separated string e.g. "en:e407|en:e950|en:e952"
        "additives_tags":       "|".join(product.get("additives_tags", [])),
    }


# ── Save ──────────────────────────────────────────────────────────────────────

def save_raw(products: list[dict], category: str, timestamp: str) -> None:
    """Save raw API response to data/raw/ as JSON."""
    filename = f"raw_{category}_{timestamp}.json"
    path = os.path.join(RAW_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    print(f"  Raw JSON saved -> {filename}")


def save_sample(df: pd.DataFrame, timestamp: str) -> None:
    """Save combined flat CSV to data/sample/."""
    filename = f"sample_all_{timestamp}.csv"
    path = os.path.join(SAMPLE_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # utf-8-sig for Excel compatibility
    print(f"  Sample CSV saved -> {filename}  ({len(df)} rows, {len(df.columns)} columns)")


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
            wait = 15 if category == "beverages" else 5
            print(f"  Pausing {wait}s before '{category}'...")
            import time; time.sleep(wait)
        products = fetch_category(category)
        save_raw(products, category, timestamp)

        rows = [flatten_product(p, category) for p in products]
        all_rows.extend(rows)
        print()

    df = pd.DataFrame(all_rows)
    save_sample(df, timestamp)

    print(f"\nDone. {len(df)} total products across {len(CATEGORIES)} categories.")
    print(f"Nulls per column:\n{df.isnull().sum().to_string()}\n")

    # Run summary — useful for unattended overnight runs
    print(f"{'='*50}")
    print(f"RUN SUMMARY")
    print(f"{'='*50}")
    for category in CATEGORIES:
        cat_count = len(df[df['query_category'] == category])
        status = "✓ OK" if cat_count >= 400 else "⚠ PARTIAL" if cat_count > 0 else "✗ FAILED"
        print(f"  {category:<15} {cat_count:>5} products  {status}")
    print(f"  {'TOTAL':<15} {len(df):>5} products")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
