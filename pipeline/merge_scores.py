"""
merge_scores.py
---------------
Joins v1 NLP reality score with v3 Azure Vision claim extraction
to produce the final health-washing gap metric (health_wash_score_v3).

Architecture (ADR-010):
    health_wash_score_v1  = Component A (UPF reality, 0-40pts)
                            Source: analyze.py ingredient NLP
    v3_claims             = Component B input (front-of-pack claims)
                            Source: vision_extract.py Azure OCR + LLM
    health_wash_score_v3  = Component A + B + C (full gap metric, 0-100pts)
                            Computed here by merge_scores.py

Scoring:
    Component A (0-40):  UPF reality — from health_wash_score_v1
    Component B (0-30):  Claim inflation — count of front-of-pack claims
                         weighted by claim type
    Component C (0-30):  Contradiction gap — claims present on NOVA 4
                         or Nutriscore D/E products

Half-truth bonus scoring:
    Each confirmed half-truth pattern adds 10pts to Component B
    (capped at 30 total for Component B)

Usage:
    python pipeline/merge_scores.py

Input:
    database/functional_food_radar.db  (v1 scores + product data)
    data/reference/vision_results_20260523_210131.csv
    OR data/sample/vision_results_<latest>.csv

Output:
    database/functional_food_radar.db  (updated with v3 scores)
    data/sample/merged_results_<timestamp>.csv
    data/sample/powerbi_merged_<timestamp>.csv
"""

import pandas as pd
import sqlite3
import os
import json
from datetime import datetime
from pathlib import Path

ROOT       = Path(__file__).parent.parent
SAMPLE_DIR = ROOT / "data" / "sample"
REF_DIR    = ROOT / "data" / "reference"
DB_PATH    = ROOT / "database" / "functional_food_radar.db"


# ── Claim weights for Component B ────────────────────────────────────────────
# Higher weight = more egregious claim on an unhealthy product

CLAIM_WEIGHTS = {
    "protein_claim":        3,   # most commonly abused
    "no_added_sugar":       3,   # natural sugar loophole
    "reduced_sugar":        2,   # comparative claim
    "fortification_claim":  2,   # vitamin halo
    "fibre_claim":          2,   # fibre distraction
    "probiotic_claim":      2,   # functional positioning
    "natural_claim":        2,   # clean label
    "vitalite_concept":     3,   # brand health concept
    "sustainability_halo":  1,   # green halo
    "reformulation_claim":  2,   # "new recipe" deflection
    "comparative_claim":    3,   # "X% less sugar vs market"
    "glp1_positioning":     3,   # GLP-1 trend exploitation
    "energy_claim":         1,   # tautological for energy drinks
    "no_palm_oil":          1,   # environmental halo
    "no_artificial":        1,   # clean label
    "origin_quality_claim": 1,   # artisan/origin halo
    "clean_label_claim":    2,   # minimal ingredients claim
    "artisan_claim":        1,   # hand-roasted etc
}

# ── Half-truth bonus weights ──────────────────────────────────────────────────

HALF_TRUTH_BONUS = {
    "ht_sugar_loophole":    10,
    "ht_protein_masks_fat": 10,
    "ht_fibre_distraction": 10,
    "ht_vegan_calorie_trap": 8,
}


def find_latest_vision_results():
    """Find the most recent vision results CSV across reference and sample folders."""
    files = list(REF_DIR.glob("vision_results_*.csv")) + \
            list(SAMPLE_DIR.glob("vision_results_*.csv"))
    if not files:
        raise FileNotFoundError(
            "No vision_results_*.csv found. Run vision_extract.py first."
        )
    return max(files, key=lambda f: f.stat().st_mtime)


def compute_component_b(row):
    """
    Component B: Claim inflation (0-30 points).
    Based on front-of-pack claims detected by Azure Vision.
    Higher weight for more deceptive claim types.
    """
    score = 0
    for claim, weight in CLAIM_WEIGHTS.items():
        col = f"v3_{claim}"
        if col in row.index and row[col] == True:
            score += weight
    return min(score, 30)


def compute_component_c(row):
    """
    Component C: Contradiction gap (0-30 points).
    Fires when front-of-pack claims contradict nutritional reality.
    NOVA 4 + any claim = contradiction.
    Nutriscore D/E + health claim = additional penalty.
    Comparative claim = extra penalty (misleading reference).
    """
    score = 0
    has_any_claim = row.get("component_b", 0) > 0

    if not has_any_claim:
        return 0

    # NOVA 4 with health claims
    try:
        nova = float(row.get("nova_group", 0) or 0)
    except (TypeError, ValueError):
        nova = 0

    if nova == 4.0:
        score += 15
    elif nova == 3.0:
        score += 8

    # Nutriscore D/E with health claims
    nutriscore = str(row.get("nutriscore_grade", "") or "").upper()
    if nutriscore == "E":
        score += 10
    elif nutriscore == "D":
        score += 7

    # Comparative claim extra penalty (e.g. "-32% sugar vs market average")
    if row.get("v3_comparative_claim") == True:
        score += 5

    # GLP-1 positioning on NOVA 4 — emerging pattern
    if row.get("v3_glp1_positioning") == True and nova == 4.0:
        score += 5

    return min(score, 30)


def compute_half_truth_bonus(row):
    """
    Half-truth bonus: adds to Component B when NLP-detected patterns
    are confirmed by vision (claim present + nutritional contradiction).
    """
    bonus = 0
    for col, weight in HALF_TRUTH_BONUS.items():
        if row.get(col) == True or row.get(col) == 1:
            # Only add bonus if there's also a front-of-pack claim
            if row.get("component_b", 0) > 0:
                bonus += weight
    return bonus


def classify_v3(score):
    """Map v3 score to category label."""
    if score >= 70:
        return "HIGH — strong health-washing signals"
    elif score >= 45:
        return "MEDIUM — some health-washing signals"
    elif score >= 20:
        return "LOW — minor signals"
    else:
        return "CLEAN — no significant signals"


def load_db_data(conn):
    """Load products + v1 NLP scores from SQLite."""
    df = pd.read_sql("""
        SELECT
            p.barcode, p.product_name, p.brands, p.primary_brand,
            p.query_category, p.primary_country,
            p.nova_group, p.nutriscore_grade,
            p.energy_kcal, p.sugars_100g, p.protein_100g,
            p.saturated_fat_100g, p.image_url,
            r.health_wash_score_v1,
            r.upf_markers_found,
            r.functional_claims_found,
            r.negative_claims_found,
            r.ht_sugar_loophole,
            r.ht_protein_masks_fat,
            r.ht_fibre_distraction,
            r.ht_vegan_calorie_trap
        FROM products p
        LEFT JOIN nlp_results r ON p.barcode = r.barcode
    """, conn, dtype={"barcode": str})
    return df


def update_db_v3_scores(conn, merged_df, timestamp):
    """Write v3 scores back to nlp_results table."""
    cursor = conn.cursor()
    updated = 0

    v3_cols = [
        "health_wash_score_v3", "health_wash_category_v3", "v3_claims_found"
    ]

    for _, row in merged_df[
        merged_df["health_wash_score_v3"].notna()
    ].iterrows():
        cursor.execute("""
            UPDATE nlp_results
            SET health_wash_score_v3 = ?,
                health_wash_category_v3 = ?,
                v3_claims_found = ?,
                analyzed_at = ?
            WHERE barcode = ?
        """, (
            float(row["health_wash_score_v3"]),
            str(row["health_wash_category_v3"]),
            str(row.get("v3_claims_found", "") or ""),
            timestamp,
            str(row["barcode"])
        ))
        updated += 1

    conn.commit()
    return updated


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\nFunctional Food Radar - merge_scores.py")
    print(f"Run timestamp: {timestamp}")
    print(f"Architecture: v1 NLP + v3 Vision -> health_wash_score_v3\n")

    # ── Load vision results ───────────────────────────────────────────────────
    vision_path = find_latest_vision_results()
    print(f"  Vision results: {vision_path.name}")
    vision = pd.read_csv(vision_path, dtype={"barcode": str}, low_memory=False)
    print(f"  Vision rows: {len(vision):,}")

    ocr_ok  = (vision["ocr_status"] == "success").sum()
    llm_ok  = (vision["llm_status"] == "success").sum()
    print(f"  OCR success: {ocr_ok:,} | LLM success: {llm_ok:,}")

    # ── Load DB data ──────────────────────────────────────────────────────────
    print(f"\n  Loading product + v1 data from DB...")
    conn = sqlite3.connect(DB_PATH)
    db_df = load_db_data(conn)
    print(f"  DB rows: {len(db_df):,}")

    # ── Merge on barcode ──────────────────────────────────────────────────────
    print(f"\n  Merging on barcode...")

    # Keep only v3_ columns from vision results
    v3_cols = [c for c in vision.columns if c.startswith("v3_")]
    vision_slim = vision[["barcode", "ocr_text", "ocr_status",
                           "llm_status"] + v3_cols].copy()

    merged = db_df.merge(vision_slim, on="barcode", how="left")
    vision_matched = merged["llm_status"].notna().sum()
    print(f"  Products with vision data: {vision_matched:,}")
    print(f"  Products without vision data: {(merged['llm_status'].isna()).sum():,}")

    # ── Compute v3 scores ─────────────────────────────────────────────────────
    print(f"\n  Computing health_wash_score_v3...")

    # Only score products that have both v1 and v3 data
    has_vision = merged["llm_status"] == "success"

    # Extract v3 claim list for storage
    def get_v3_claims_found(row):
        claims = []
        for col in v3_cols:
            if col in row.index and row[col] == True:
                claims.append(col.replace("v3_", ""))
        return "|".join(claims) if claims else ""

    merged["v3_claims_found"] = merged.apply(get_v3_claims_found, axis=1)

    # Component B
    merged["component_b"] = merged.apply(
        lambda row: compute_component_b(row) if has_vision[row.name] else 0,
        axis=1
    )

    # Half-truth bonus
    merged["ht_bonus"] = merged.apply(compute_half_truth_bonus, axis=1)

    # Adjusted Component B
    merged["component_b_adj"] = (merged["component_b"] +
                                  merged["ht_bonus"]).clip(upper=30)

    # Component C
    merged["component_c"] = merged.apply(
        lambda row: compute_component_c(row) if has_vision[row.name] else 0,
        axis=1
    )

    # Final v3 score
    merged["health_wash_score_v1"] = pd.to_numeric(
        merged["health_wash_score_v1"], errors="coerce"
    ).fillna(0)

    merged["health_wash_score_v3"] = merged.apply(
        lambda row: (
            row["health_wash_score_v1"] +
            row["component_b_adj"] +
            row["component_c"]
        ) if has_vision[row.name] else None,
        axis=1
    )

    merged["health_wash_category_v3"] = merged["health_wash_score_v3"].apply(
        lambda s: classify_v3(s) if pd.notna(s) else None
    )

    # ── Summary statistics ────────────────────────────────────────────────────
    scored = merged[merged["health_wash_score_v3"].notna()].copy()
    scored["health_wash_score_v3"] = pd.to_numeric(
        scored["health_wash_score_v3"], errors="coerce"
    )

    print(f"\n  -- v3 Score Summary ------------------------------------------")
    print(f"  Products with v3 score: {len(scored):,}")

    dist = scored["health_wash_category_v3"].value_counts()
    print(f"\n  Score distribution:")
    for cat, n in dist.items():
        print(f"    {cat:<45} {n:,}")

    print(f"\n  Score uplift (v1 → v3):")
    uplift = scored["health_wash_score_v3"] - scored["health_wash_score_v1"]
    print(f"    Mean uplift:   {uplift.mean():.1f} points")
    print(f"    Max uplift:    {uplift.max():.1f} points")
    print(f"    Products with uplift > 20:  {(uplift > 20).sum():,}")

    print(f"\n  Top 15 products by v3 score:")
    top = scored.nlargest(15, "health_wash_score_v3")[
        ["product_name", "brands", "health_wash_score_v1",
         "health_wash_score_v3", "v3_claims_found"]
    ]
    pd.set_option("display.max_colwidth", 35)
    print("  " + top.to_string().replace("\n", "\n  "))

    print(f"\n  Top 10 brands by avg v3 score (min 5 products with vision):")
    brand_stats = scored.groupby("primary_brand").agg(
        avg_v3=("health_wash_score_v3", "mean"),
        avg_v1=("health_wash_score_v1", "mean"),
        n=("barcode", "count")
    ).reset_index()
    brand_stats = brand_stats[brand_stats["n"] >= 5].sort_values(
        "avg_v3", ascending=False
    ).head(10)
    for _, row in brand_stats.iterrows():
        uplift_brand = row["avg_v3"] - row["avg_v1"]
        print(f"    {str(row['primary_brand']):<25} "
              f"v1={row['avg_v1']:.1f} → v3={row['avg_v3']:.1f} "
              f"(+{uplift_brand:.1f})  n={int(row['n'])}")

    # ── Half-truth summary ────────────────────────────────────────────────────
    print(f"\n  Half-truth patterns confirmed by vision:")
    for col, label in [
        ("ht_sugar_loophole",    "HT-1 sugar loophole"),
        ("ht_protein_masks_fat", "HT-2 protein masks fat"),
        ("ht_fibre_distraction", "HT-3 fibre distraction"),
        ("ht_vegan_calorie_trap","HT-4 vegan calorie trap"),
    ]:
        ht_with_claims = scored[
            (scored[col].isin([True, 1])) &
            (scored["component_b"] > 0)
        ]
        print(f"    {label}: {len(ht_with_claims):,} confirmed")

    # ── Write v3 scores to DB ─────────────────────────────────────────────────
    print(f"\n  Writing v3 scores to database...")
    updated = update_db_v3_scores(conn, merged, timestamp)
    print(f"  Updated {updated:,} rows in nlp_results")
    conn.close()

    # ── Save merged CSV ───────────────────────────────────────────────────────
    output_path = SAMPLE_DIR / f"merged_results_{timestamp}.csv"
    merged.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n  Saved -> merged_results_{timestamp}.csv")
    print(f"  ({len(merged):,} rows)")

    # Power BI friendly export — scored products only
    pbi_cols = [
        "barcode", "product_name", "brands", "primary_brand",
        "query_category", "primary_country", "nova_group", "nutriscore_grade",
        "energy_kcal", "sugars_100g", "protein_100g", "saturated_fat_100g",
        "image_url", "health_wash_score_v1", "health_wash_score_v3",
        "health_wash_category_v3", "component_b_adj", "component_c",
        "v3_claims_found", "upf_markers_found",
        "ht_sugar_loophole", "ht_protein_masks_fat",
        "ht_fibre_distraction", "ht_vegan_calorie_trap",
    ] + [c for c in v3_cols if c in merged.columns]

    pbi_cols = [c for c in pbi_cols if c in merged.columns]
    pbi_df = scored[pbi_cols].copy()
    pbi_path = SAMPLE_DIR / f"powerbi_merged_{timestamp}.csv"
    pbi_df.to_csv(pbi_path, index=False, encoding="utf-8-sig")
    print(f"  Power BI export -> powerbi_merged_{timestamp}.csv")
    print(f"  ({len(pbi_df):,} rows)\n")
    print(f"  Done. health_wash_score_v3 is now in the database.\n")


if __name__ == "__main__":
    main()