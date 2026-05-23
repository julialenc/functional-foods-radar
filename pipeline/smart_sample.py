"""
smart_sample.py
---------------
Generates the priority image sample for v3 Azure Vision analysis.

Three-tier sampling strategy (from practitioner feedback + ADR-010):

TIER 1 — Named priority brands (sampled regardless of score)
    Brands where health-washing hypothesis is known a priori.
    15 products per brand, maximally score-diverse selection.
    These are the analytically most interesting brands.

TIER 2 — NOVA 4 + Nutriscore D/E + functional claims
    Products where the data signals contradiction.
    Structurally suspicious: bad nutrition + health claim language detected.
    8 products per brand, brands with >= 5 products.

TIER 3 — High UPF reality score brands
    Brands where v1 NLP flags heavy ultra-processing.
    3 products per brand, avg health_wash_score_v1 >= 20, n >= 10.

Output:
    data/sample/smart_sample_<timestamp>.csv
    - barcode, product_name, brands, image_url
    - tier (1/2/3), sampling_reason
    - all nutritional + NLP columns for context

Usage:
    python pipeline/smart_sample.py

Prerequisites:
    - database/functional_food_radar.db must exist with v2 analyzed data
    - Run load_bulk_direct.py first if DB is empty

Azure budget guidance:
    100 CHF total credits (expire May 31 2026)
    Tier 1 Azure AI Vision OCR: ~1.50 CHF / 1,000 images
    Tier 2 GPT-4o-mini text: ~0.50 CHF / 1,000 calls
    Target: 7,000-10,000 images = ~15-25 CHF total
    Set cost alert at 80 CHF before any API calls.
"""

import sqlite3
import pandas as pd
import os
from datetime import datetime

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH    = os.path.join(ROOT, "database", "functional_food_radar.db")
SAMPLE_DIR = os.path.join(ROOT, "data", "sample")

# ── Tier 1: Named priority brands ────────────────────────────────────────────
# These are sampled regardless of score.
# Based on practitioner input: known health-washing suspects.

TIER1_BRANDS = [
    # Swiss / European premium — half-truth heartland
    "emmi", "chiefs",
    # Natural/fruit positioning
    "innocent", "nakd",
    # Plant milk
    "alpro", "oatly",
    # Breakfast / snack fortification
    "belvita", "gerble", "nature valley",
    # Cereal
    "kellogg's", "special k",
    # Probiotic drinks
    "actimel", "danone",
    # High-protein
    "hipro", "fairlife",
    # Confectionery with protein claims
    "mars", "snickers", "bounty", "twix",
    # Conglomerates
    "nestle",
]

# ── Tier 2: NOVA 4 + D/E + functional claims ─────────────────────────────────
TIER2_NOVA      = 4.0
TIER2_NUTRISCORE = ("D", "E")
TIER2_MIN_N     = 5
TIER2_SAMPLE_N  = 8    # was 6

# ── Tier 3: High UPF score brands ────────────────────────────────────────────
TIER3_MIN_AVG_SCORE = 20
TIER3_MIN_N         = 10
TIER3_SAMPLE_N      = 5  # was 3

# ── Per-brand sample size ─────────────────────────────────────────────────────
TIER1_SAMPLE_N = 15  # was 5


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_products_with_scores(conn):
    """Load all products with NLP scores and image URLs."""
    df = pd.read_sql("""
        SELECT
            p.barcode, p.product_name, p.brands, p.primary_brand,
            p.query_category, p.off_categories, p.primary_country,
            p.nova_group, p.nutriscore_grade,
            p.energy_kcal, p.fat_100g, p.saturated_fat_100g,
            p.carbs_100g, p.sugars_100g, p.protein_100g, p.salt_100g,
            p.image_url,
            r.health_wash_score_v1,
            r.upf_markers_found,
            r.functional_claims_found,
            r.negative_claims_found,
            r.has_artificial_sweetener,
            r.ht_sugar_loophole,
            r.ht_protein_masks_fat,
            r.ht_fibre_distraction,
            r.ht_vegan_calorie_trap
        FROM products p
        LEFT JOIN nlp_results r ON p.barcode = r.barcode
        WHERE p.image_url IS NOT NULL
          AND p.image_url NOT LIKE '%/invalid/%'
          AND p.image_url != ''
    """, conn)
    return df


def sample_diverse(group, n, score_col="health_wash_score_v1"):
    """
    Select n products from a group with maximum score diversity.
    Takes products spread across the score distribution rather than
    just the top n — gives a representative sample per brand.
    """
    if len(group) <= n:
        return group
    group = group.dropna(subset=[score_col]).sort_values(score_col)
    indices = [int(i * (len(group) - 1) / (n - 1)) for i in range(n)]
    return group.iloc[indices]


def sample_tier1(df):
    """Tier 1: named brands, 5 products each, score-diverse."""
    print(f"\n  TIER 1 — Named priority brands ({len(TIER1_BRANDS)} brands, {TIER1_SAMPLE_N} products each)")
    results = []
    for brand in TIER1_BRANDS:
        group = df[df["primary_brand"] == brand].copy()
        if len(group) == 0:
            print(f"    {brand:<25} 0 products — MISSING from DB")
            continue
        sampled = sample_diverse(group, TIER1_SAMPLE_N)
        sampled = sampled.copy()
        sampled["tier"] = 1
        sampled["sampling_reason"] = f"tier1_named_brand:{brand}"
        results.append(sampled)
        print(f"    {brand:<25} {len(group):>5} in DB → {len(sampled)} sampled")
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def sample_tier2(df, already_sampled_barcodes):
    """Tier 2: NOVA 4 + D/E nutriscore + functional claims, by brand."""
    print(f"\n  TIER 2 — NOVA 4 + Nutriscore D/E + functional claims")

    mask = (
        (df["nova_group"] == TIER2_NOVA) &
        (df["nutriscore_grade"].str.upper().isin(TIER2_NUTRISCORE)) &
        (df["functional_claims_found"].notna()) &
        (df["functional_claims_found"] != "") &
        (~df["barcode"].isin(already_sampled_barcodes))
    )
    pool = df[mask].copy()
    print(f"    Pool: {len(pool):,} products match NOVA4 + D/E + claims criteria")

    results = []
    brand_counts = pool["primary_brand"].value_counts()
    eligible_brands = brand_counts[brand_counts >= TIER2_MIN_N].index

    for brand in eligible_brands[:500]:  # was 200
        group = pool[pool["primary_brand"] == brand]
        sampled = sample_diverse(group, TIER2_SAMPLE_N)
        sampled = sampled.copy()
        sampled["tier"] = 2
        sampled["sampling_reason"] = f"tier2_nova4_DE_claims:{brand}"
        results.append(sampled)

    tier2_df = pd.concat(results, ignore_index=True) if results else pd.DataFrame()
    print(f"    {len(eligible_brands)} eligible brands → {len(tier2_df)} products sampled")
    return tier2_df


def sample_tier3(df, already_sampled_barcodes):
    """Tier 3: high UPF reality score brands not already captured."""
    print(f"\n  TIER 3 — High UPF reality score brands")

    pool = df[
        (~df["barcode"].isin(already_sampled_barcodes)) &
        (df["health_wash_score_v1"].notna())
    ].copy()

    brand_stats = pool.groupby("primary_brand").agg(
        avg_score=("health_wash_score_v1", "mean"),
        n=("barcode", "count")
    ).reset_index()

    eligible = brand_stats[
        (brand_stats["avg_score"] >= TIER3_MIN_AVG_SCORE) &
        (brand_stats["n"] >= TIER3_MIN_N)
    ].sort_values("avg_score", ascending=False)

    print(f"    {len(eligible)} brands with avg_score >= {TIER3_MIN_AVG_SCORE}, n >= {TIER3_MIN_N}")

    results = []
    for _, row in eligible.head(150).iterrows():  # was 50
        brand = row["primary_brand"]
        group = pool[pool["primary_brand"] == brand]
        sampled = sample_diverse(group, TIER3_SAMPLE_N)
        sampled = sampled.copy()
        sampled["tier"] = 3
        sampled["sampling_reason"] = f"tier3_high_upf_score:{brand}"
        results.append(sampled)

    tier3_df = pd.concat(results, ignore_index=True) if results else pd.DataFrame()
    print(f"    {len(tier3_df)} products sampled from {min(len(eligible), 50)} brands")
    return tier3_df

def sample_tier4_halftruth(df, already_sampled_barcodes):
    """Tier 4: dedicated half-truth pattern quota sampling."""
    print(f"\n  TIER 4 — Half-truth quota sampling")
    results = []
    patterns = [
        ("ht_sugar_loophole",    "HT-1 sugar loophole",    100),
        ("ht_fibre_distraction", "HT-3 fibre distraction", 100),
    ]
    for col, label, target in patterns:
        pool = df[
            (df[col] == True) &
            (~df["barcode"].isin(already_sampled_barcodes))
        ].copy()
        sampled = pool.sample(min(target, len(pool)), random_state=42)
        sampled = sampled.copy()
        sampled["tier"] = 4
        sampled["sampling_reason"] = f"tier4_{col}"
        results.append(sampled)
        print(f"    {label}: {len(pool):,} available → {len(sampled)} sampled")
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\nFunctional Food Radar - smart_sample.py")
    print(f"Run timestamp: {timestamp}")
    print(f"DB: {DB_PATH}\n")

    if not os.path.exists(DB_PATH):
        print("ERROR: Database not found. Run load_bulk_direct.py first.")
        return

    conn = get_conn()
    print("  Loading products with image URLs from DB...")
    df = load_products_with_scores(conn)
    conn.close()

    print(f"  Products with valid image URLs: {len(df):,}")

    # Run three tiers
    tier1 = sample_tier1(df)
    tier1_barcodes = set(tier1["barcode"].tolist()) if len(tier1) else set()

    tier2 = sample_tier2(df, tier1_barcodes)
    tier2_barcodes = set(tier2["barcode"].tolist()) if len(tier2) else set()

    tier3 = sample_tier3(df, tier1_barcodes | tier2_barcodes)
    tier3_barcodes = set(tier3["barcode"].tolist()) if len(tier3) else set()

    tier4 = sample_tier4_halftruth(df, tier1_barcodes | tier2_barcodes | tier3_barcodes)
    tier4_barcodes = set(tier4["barcode"].tolist()) if len(tier4) else set()

    # Combine
    all_tiers = []
    for t in [tier1, tier2, tier3, tier4]:
        if len(t):
            all_tiers.append(t)

    if not all_tiers:
        print("\nERROR: No products sampled. Check DB content.")
        return

    sample = pd.concat(all_tiers, ignore_index=True)
    sample = sample.drop_duplicates(subset=["barcode"])

    # Summary
    print(f"\n  -- Summary --------------------------------------------------")
    print(f"  Total sampled:  {len(sample):,} products")
    print(f"  Tier 1:         {(sample['tier'] == 1).sum():,}")
    print(f"  Tier 2:         {(sample['tier'] == 2).sum():,}")
    print(f"  Tier 3:         {(sample['tier'] == 3).sum():,}")
    print(f"\n  Estimated Azure cost:")
    n = len(sample)
    ocr_cost  = n * 1.50 / 1000
    llm_cost  = n * 0.50 / 1000
    print(f"    OCR (Azure Vision Read API): {ocr_cost:.2f} CHF")
    print(f"    LLM (GPT-4o-mini text):      {llm_cost:.2f} CHF")
    print(f"    Total estimate:              {ocr_cost + llm_cost:.2f} CHF")
    print(f"    Remaining budget (100 CHF):  {100 - ocr_cost - llm_cost:.2f} CHF")

    # Half-truth breakdown
    print(f"\n  Half-truth patterns in sample:")
    for col, label in [
        ("ht_sugar_loophole",    "HT-1 sugar loophole"),
        ("ht_protein_masks_fat", "HT-2 protein masks fat"),
        ("ht_fibre_distraction", "HT-3 fibre distraction"),
        ("ht_vegan_calorie_trap","HT-4 vegan calorie trap"),
    ]:
        if col in sample.columns:
            n_ht = sample[col].sum()
            print(f"    {label}: {int(n_ht):,}")

    # Save
    output_path = os.path.join(SAMPLE_DIR, f"smart_sample_{timestamp}.csv")
    sample.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n  Saved -> smart_sample_{timestamp}.csv")
    print(f"  ({len(sample):,} rows, {len(sample.columns)} columns)")
    print(f"\n  Next step: python pipeline/vision_extract.py")
    print(f"  Input: smart_sample_{timestamp}.csv")
    print(f"  Set Azure cost alert at 80 CHF before running.\n")


if __name__ == "__main__":
    main()