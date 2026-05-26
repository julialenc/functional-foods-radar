"""
tag_claims.py
-------------
Computes claim taxonomy and EU Regulation 1169/2011 nutritional warnings.
Writes results back to nlp_results table and updates Power BI export.

TWO-CUT CLAIM TAXONOMY (from practitioner feedback, May 2026):

Cut 1 — claim_category_1 (broad):
    FUNCTIONAL  — "has something" or "does something"
                  protein, fiber, probiotic, vitamin, immune, energy
    FREE_OF     — "doesn't have something" or "has little of something"
                  no added sugar, reduced sugar, low fat, no artificial
    BIO         — organic, natural, clean label, no palm oil
    OTHER       — heritage, gender targeting, comparative, sustainability
    NO_CLAIM    — no front-of-pack claims detected

Cut 2 — claim_category_2 (sub-group):
    protein | fiber | gut_health | vitamins | immune | energy
    sugar_free | fat_free | no_artificial | clean_label
    organic | natural
    comparative | heritage | sustainability | other
    none

EU REGULATION 1169/2011 WARNINGS (per 100g solid / per 100ml liquid):
    HIGH sugar:        >22.5g (solid) / >11.25g (liquid)
    HIGH saturated fat:>5g    (solid) / >3g     (liquid)
    HIGH fat:          >17.5g (solid) / >7.5g   (liquid)
    HIGH salt:         >1.25g (solid) / >0.625g (liquid)

Liquid detection: products with energy_kcal < 100 kcal/100ml treated
as liquids. Products with energy_kcal >= 100 treated as solids.

Usage:
    python pipeline/tag_claims.py

Output:
    - Updates nlp_results table in SQLite with new columns
    - Saves data/sample/powerbi_tagged_<timestamp>.csv
"""

import sqlite3
import pandas as pd
import os
from datetime import datetime
from pathlib import Path

ROOT       = Path(__file__).parent.parent
DB_PATH    = ROOT / "database" / "functional_food_radar.db"
SAMPLE_DIR = ROOT / "data" / "sample"

# ── EU Regulation 1169/2011 thresholds ───────────────────────────────────────
# Source: EU Reg 1169/2011 Annex XIII + UK FSA traffic light (identical)
# Applied per 100g (solids) or per 100ml (liquids)
# US products assessed against same benchmarks — see OBS-027

EU_THRESHOLDS = {
    "solid": {
        "sugar":        {"high": 22.5, "low": 5.0},
        "saturated_fat":{"high": 5.0,  "low": 1.5},
        "fat":          {"high": 17.5, "low": 3.0},
        "salt":         {"high": 1.25, "low": 0.3},
    },
    "liquid": {
        "sugar":        {"high": 11.25, "low": 2.5},
        "saturated_fat":{"high": 3.0,   "low": 0.75},
        "fat":          {"high": 7.5,   "low": 1.5},
        "salt":         {"high": 0.625, "low": 0.3},
    }
}

# Liquid detection threshold (kcal/100ml)
LIQUID_KCAL_THRESHOLD = 100

# ── Claim taxonomy mappings ───────────────────────────────────────────────────

# Maps claim keywords to (category_1, category_2)
CLAIM_TAXONOMY = {
    # FUNCTIONAL claims
    "protein_claim":          ("FUNCTIONAL", "protein"),
    "fibre_claim":            ("FUNCTIONAL", "fiber"),
    "probiotic_claim":        ("FUNCTIONAL", "gut_health"),
    "prebiotic_claim":        ("FUNCTIONAL", "gut_health"),
    "immune_claim":           ("FUNCTIONAL", "immune"),
    "fortification_claim":    ("FUNCTIONAL", "vitamins"),
    "energy_claim":           ("FUNCTIONAL", "energy"),
    "vitalite_concept":       ("FUNCTIONAL", "vitamins"),

    # FREE_OF claims
    "no_added_sugar":         ("FREE_OF", "sugar_free"),
    "reduced_sugar":          ("FREE_OF", "sugar_free"),
    "no_artificial":          ("FREE_OF", "no_artificial"),
    "gluten_free_claim":      ("FREE_OF", "no_artificial"),
    "dairy_free_claim":       ("FREE_OF", "no_artificial"),
    "glp1_positioning":       ("FREE_OF", "fat_free"),

    # BIO claims
    "natural_claim":          ("BIO", "natural"),
    "organic_claim":          ("BIO", "organic"),
    "clean_label_claim":      ("BIO", "clean_label"),
    "no_palm_oil":            ("BIO", "clean_label"),
    "minimal_ingredients_claim": ("BIO", "clean_label"),
    "plant_based_claim":      ("BIO", "natural"),
    "vegan_claim":            ("BIO", "natural"),

    # OTHER claims
    "comparative_claim":      ("OTHER", "comparative"),
    "reformulation_claim":    ("OTHER", "comparative"),
    "heritage_claim":         ("OTHER", "heritage"),
    "gender_targeting_claim": ("OTHER", "other"),
    "sustainability_halo":    ("OTHER", "sustainability"),
    "origin_quality_claim":   ("OTHER", "heritage"),
    "artisan_claim":          ("OTHER", "heritage"),
}

# Priority order for cut 1 (if multiple categories present)
CATEGORY_1_PRIORITY = ["FUNCTIONAL", "FREE_OF", "BIO", "OTHER"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_liquid(kcal):
    """Detect if product is liquid based on energy density."""
    try:
        return float(kcal) < LIQUID_KCAL_THRESHOLD
    except (TypeError, ValueError):
        return False


def compute_claim_categories(v3_claims_str, functional_claims_str,
                              no_claims_detected):
    """
    Compute claim_category_1 and claim_category_2 from claim strings.
    Uses v3 vision claims first, falls back to NLP claims.
    """
    # No claims detected
    if no_claims_detected == True or no_claims_detected == 1:
        # Double check — if v3 claims string is also empty
        claims_str = str(v3_claims_str or "") + str(functional_claims_str or "")
        if not claims_str.strip():
            return "NO_CLAIM", "none"

    # Collect all claim keywords present
    claims_str = str(v3_claims_str or "") + "|" + str(functional_claims_str or "")
    claims_present = set(claims_str.lower().split("|"))
    claims_present.discard("")
    claims_present.discard("nan")

    # Map to taxonomy
    categories_found = set()
    subcategories_found = []

    for claim_key, (cat1, cat2) in CLAIM_TAXONOMY.items():
        if claim_key in claims_present:
            categories_found.add(cat1)
            if cat2 not in subcategories_found:
                subcategories_found.append(cat2)

    if not categories_found:
        return "NO_CLAIM", "none"

    # Pick highest priority category_1
    for cat in CATEGORY_1_PRIORITY:
        if cat in categories_found:
            cat1_result = cat
            break
    else:
        cat1_result = list(categories_found)[0]

    # Primary subcategory
    cat2_result = subcategories_found[0] if subcategories_found else "other"

    return cat1_result, cat2_result


def compute_eu_warnings(row):
    """
    Compute EU Regulation 1169/2011 nutritional warnings.
    Returns pipe-separated string of warnings, or empty string.
    """
    liquid = is_liquid(row.get("energy_kcal"))
    thresholds = EU_THRESHOLDS["liquid"] if liquid else EU_THRESHOLDS["solid"]
    warnings = []

    nutrient_map = {
        "sugar":         "sugars_100g",
        "saturated_fat": "saturated_fat_100g",
        "fat":           "fat_100g",
        "salt":          "salt_100g",
    }

    nutrient_labels = {
        "sugar":         "High in sugar",
        "saturated_fat": "High in saturated fat",
        "fat":           "High in fat",
        "salt":          "High in salt",
    }

    for nutrient, col in nutrient_map.items():
        try:
            value = float(row.get(col))
            if value > thresholds[nutrient]["high"]:
                warnings.append(nutrient_labels[nutrient])
        except (TypeError, ValueError):
            continue

    return "|".join(warnings)


def compute_claim_contradiction(row):
    """
    Detect claim-nutrition contradictions (Yellow flags).
    Only fires when a claim is present AND nutrition contradicts it.
    Returns pipe-separated string of contradictions.
    """
    contradictions = []
    claims = str(row.get("v3_claims_found") or "") + \
             str(row.get("functional_claims_found") or "")
    warnings = str(row.get("eu_warnings") or "")
    liquid = is_liquid(row.get("energy_kcal"))
    thresholds = EU_THRESHOLDS["liquid"] if liquid else EU_THRESHOLDS["solid"]

    # Protein claim + high sugar or high sat fat
    if "protein_claim" in claims:
        try:
            if float(row.get("sugars_100g")) > thresholds["sugar"]["high"]:
                contradictions.append("Protein claim · also high in sugar")
        except (TypeError, ValueError):
            pass
        try:
            if float(row.get("saturated_fat_100g")) > thresholds["saturated_fat"]["high"]:
                contradictions.append("Protein claim · also high in saturated fat")
        except (TypeError, ValueError):
            pass

    # No added sugar claim + high actual sugar
    if "no_added_sugar" in claims or "reduced_sugar" in claims:
        try:
            if float(row.get("sugars_100g")) > thresholds["sugar"]["high"]:
                contradictions.append("Low/no sugar claim · sugar still high")
        except (TypeError, ValueError):
            pass

    # Natural/clean claim + NOVA 4
    if any(c in claims for c in ["natural_claim", "clean_label_claim", "organic_claim"]):
        try:
            if float(row.get("nova_group")) == 4.0:
                contradictions.append("Natural claim · ultra-processed (NOVA 4)")
        except (TypeError, ValueError):
            pass

    # Fibre claim + high sugar + NOVA 4
    if "fibre_claim" in claims:
        try:
            if (float(row.get("nova_group")) == 4.0 and
                    float(row.get("sugars_100g")) > thresholds["sugar"]["high"]):
                contradictions.append("Fibre claim · also high in sugar")
        except (TypeError, ValueError):
            pass

    return "|".join(contradictions)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\nFunctional Food Radar - tag_claims.py")
    print(f"Run timestamp: {timestamp}")
    print(f"Thresholds: EU Regulation 1169/2011 (see OBS-027)\n")

    # Load from DB
    conn = sqlite3.connect(DB_PATH)
    print("  Loading products + NLP results from DB...")

    df = pd.read_sql("""
        SELECT
            p.barcode, p.product_name, p.brands, p.primary_brand,
            p.nova_group, p.nutriscore_grade,
            p.energy_kcal, p.fat_100g, p.saturated_fat_100g,
            p.sugars_100g, p.protein_100g, p.salt_100g,
            p.query_category, p.primary_country,
            r.health_wash_score_v1, r.health_wash_score_v3,
            r.health_wash_category_v3,
            r.functional_claims_found, r.negative_claims_found,
            r.v3_claims_found, r.v3_no_claims_detected,
            r.ht_sugar_loophole, r.ht_protein_masks_fat,
            r.ht_fibre_distraction, r.ht_vegan_calorie_trap,
            r.upf_markers_found
        FROM products p
        LEFT JOIN nlp_results r ON p.barcode = r.barcode
    """, conn, dtype={"barcode": str})

    print(f"  Loaded {len(df):,} rows")

    # ── Compute claim taxonomy ────────────────────────────────────────────────
    print("\n  Computing claim taxonomy (2-cut)...")

    results = df.apply(
        lambda row: compute_claim_categories(
            row.get("v3_claims_found"),
            row.get("functional_claims_found"),
            row.get("v3_no_claims_detected")
        ), axis=1
    )
    df["claim_category_1"] = [r[0] for r in results]
    df["claim_category_2"] = [r[1] for r in results]

    # Distribution
    print(f"\n  Cut 1 distribution:")
    for cat, n in df["claim_category_1"].value_counts().items():
        pct = n / len(df) * 100
        print(f"    {cat:<15} {n:>10,} ({pct:.1f}%)")

    print(f"\n  Cut 2 top subcategories:")
    for cat, n in df["claim_category_2"].value_counts().head(10).items():
        pct = n / len(df) * 100
        print(f"    {cat:<20} {n:>10,} ({pct:.1f}%)")

    # ── Compute EU warnings ───────────────────────────────────────────────────
    print("\n  Computing EU 1169/2011 nutritional warnings...")
    df["eu_warnings"] = df.apply(compute_eu_warnings, axis=1)

    warned = (df["eu_warnings"] != "").sum()
    print(f"  Products with at least one EU warning: {warned:,} ({warned/len(df)*100:.1f}%)")

    # Warning breakdown
    all_warnings = []
    for w in df["eu_warnings"].dropna():
        if w:
            all_warnings.extend(w.split("|"))
    from collections import Counter
    for warning, count in Counter(all_warnings).most_common():
        print(f"    {warning:<35} {count:,}")

    # ── Compute claim contradictions ──────────────────────────────────────────
    print("\n  Computing claim-nutrition contradictions...")
    df["claim_contradiction"] = df.apply(compute_claim_contradiction, axis=1)

    contradicted = (df["claim_contradiction"] != "").sum()
    print(f"  Products with claim contradictions: {contradicted:,}")

    all_contras = []
    for c in df["claim_contradiction"].dropna():
        if c:
            all_contras.extend(c.split("|"))
    for contra, count in Counter(all_contras).most_common():
        print(f"    {contra:<45} {count:,}")

    # ── Write to DB ───────────────────────────────────────────────────────────
    print("\n  Writing tags to database...")

    cursor = conn.cursor()

    # Add columns if they don't exist
    for col, dtype in [
        ("claim_category_1",  "TEXT"),
        ("claim_category_2",  "TEXT"),
        ("eu_warnings",       "TEXT"),
        ("claim_contradiction","TEXT"),
    ]:
        try:
            cursor.execute(
                f"ALTER TABLE nlp_results ADD COLUMN {col} {dtype}"
            )
            print(f"    Added column: {col}")
        except Exception:
            pass  # Column already exists

    # Update rows
    updated = 0
    batch = []
    for _, row in df.iterrows():
        batch.append((
            row["claim_category_1"],
            row["claim_category_2"],
            row["eu_warnings"],
            row["claim_contradiction"],
            row["barcode"]
        ))
        if len(batch) >= 10000:
            cursor.executemany("""
                UPDATE nlp_results
                SET claim_category_1   = ?,
                    claim_category_2   = ?,
                    eu_warnings        = ?,
                    claim_contradiction = ?
                WHERE barcode = ?
            """, batch)
            updated += len(batch)
            batch = []
            print(f"    Updated {updated:,} rows...")

    if batch:
        cursor.executemany("""
            UPDATE nlp_results
            SET claim_category_1   = ?,
                claim_category_2   = ?,
                eu_warnings        = ?,
                claim_contradiction = ?
            WHERE barcode = ?
        """, batch)
        updated += len(batch)

    conn.commit()
    print(f"  Total updated: {updated:,} rows")

    # ── Power BI export ───────────────────────────────────────────────────────
    print("\n  Saving Power BI export...")

    pbi_cols = [
        "barcode", "product_name", "brands", "primary_brand",
        "query_category", "primary_country",
        "nova_group", "nutriscore_grade",
        "energy_kcal", "fat_100g", "saturated_fat_100g",
        "sugars_100g", "protein_100g", "salt_100g",
        "health_wash_score_v1", "health_wash_score_v3",
        "health_wash_category_v3",
        "claim_category_1", "claim_category_2",
        "eu_warnings", "claim_contradiction",
        "v3_claims_found", "functional_claims_found",
        "ht_sugar_loophole", "ht_protein_masks_fat",
        "ht_fibre_distraction", "ht_vegan_calorie_trap",
        "upf_markers_found",
    ]

    pbi_df = df[[c for c in pbi_cols if c in df.columns]].copy()
    output_path = SAMPLE_DIR / f"powerbi_tagged_{timestamp}.csv"
    pbi_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"  Saved -> powerbi_tagged_{timestamp}.csv")
    print(f"  ({len(pbi_df):,} rows, {len(pbi_df.columns)} columns)")

    conn.close()
    print(f"\n  Done. New columns in nlp_results:")
    print(f"    claim_category_1   — FUNCTIONAL / FREE_OF / BIO / OTHER / NO_CLAIM")
    print(f"    claim_category_2   — protein / fiber / gut_health / vitamins / ...")
    print(f"    eu_warnings        — High in sugar | High in saturated fat | ...")
    print(f"    claim_contradiction— Protein claim · also high in sugar | ...")
    print(f"\n  Next step: python app.py (Streamlit reads new columns)\n")


if __name__ == "__main__":
    main()