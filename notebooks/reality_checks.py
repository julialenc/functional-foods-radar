"""
reality_checks.py
-----------------
Four sanity checks on the clean CSV produced by clean.py.
This is an exploratory script, not part of the production pipeline.
Results feed into docs/DATA_OBSERVATIONS.md.
 
Checks:
    1. Calorie plausibility by category
       Snacks:    400-550 kcal/100g expected
       Beverages:   0-100 kcal/100g expected
       Cereals:   330-420 kcal/100g expected
 
    2. Sugar cannot exceed carbs
       sugars_100g must always be <= carbs_100g
 
    3. Fat components must sum correctly
       saturated_fat_100g must always be <= fat_100g
 
    4. Pack size sanity (free text parsing)
       Flags obviously wrong quantities:
       - Beverages claiming > 5000ml or > 5000g
       - Solids claiming < 5g or > 10000g
 
Usage:
    python notebooks/reality_checks.py
"""
 
import pandas as pd
import os
import re
 
# -- Paths --------------------------------------------------------------------
 
ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(ROOT, "data", "sample")
 
# -- Helpers ------------------------------------------------------------------
 
def find_latest_clean(sample_dir):
    """Auto-detect the most recently created clean_*.csv file."""
    files = [
        f for f in os.listdir(sample_dir)
        if f.startswith("clean_") and f.endswith(".csv")
    ]
    if not files:
        raise FileNotFoundError(
            f"No clean_*.csv found in {sample_dir}. "
            "Run clean.py first."
        )
    files.sort(reverse=True)
    return os.path.join(sample_dir, files[0])
 
 
def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
 
 
def print_flagged(df, cols, check_name):
    """Print flagged rows with relevant columns."""
    display_cols = ["product_name", "brands", "query_category"] + [
        c for c in cols if c in df.columns
    ]
    if len(df) == 0:
        print(f"  PASS - No violations found")
    else:
        print(f"  FAIL - {len(df)} violation(s) found:\n")
        print("  " + df[display_cols].to_string().replace("\n", "\n  "))
 
 
# -- Check 1: Calorie plausibility by category --------------------------------
 
KCAL_RANGES = {
    "snacks":    (50,  700),   # wide range: waters to chocolate
    "beverages": (0,   200),   # 200 catches energy drinks
    "cereals":   (50,  600),   # wide: plain oats to granola
}
 
def check_calories(df):
    print_section("CHECK 1 — Calorie plausibility by category")
 
    flagged_all = []
 
    for category, (low, high) in KCAL_RANGES.items():
        subset = df[
            (df["query_category"] == category) &
            (df["energy_kcal"].notna())
        ]
        flagged = subset[
            (subset["energy_kcal"] < low) |
            (subset["energy_kcal"] > high)
        ].copy()
        flagged["expected_range"] = f"{low}-{high} kcal"
 
        if len(flagged):
            print(f"\n  Category '{category}' — "
                  f"{len(flagged)} product(s) outside {low}-{high} kcal/100g:")
            cols = ["product_name", "brands", "energy_kcal", "expected_range"]
            print("  " + flagged[cols].to_string().replace("\n", "\n  "))
        else:
            print(f"  Category '{category}' — PASS (range {low}-{high} kcal)")
 
        flagged_all.append(flagged)
 
    total = sum(len(f) for f in flagged_all)
    print(f"\n  Total flagged: {total}")
    return total
 
 
# -- Check 2: Sugar cannot exceed carbs ---------------------------------------
 
def check_sugar_vs_carbs(df):
    print_section("CHECK 2 — Sugar cannot exceed carbs")
    print("  Rule: sugars_100g must be <= carbs_100g")
 
    both_present = df[
        df["sugars_100g"].notna() & df["carbs_100g"].notna()
    ]
    flagged = both_present[
        both_present["sugars_100g"] > both_present["carbs_100g"]
    ].copy()
    flagged["excess"] = (
        flagged["sugars_100g"] - flagged["carbs_100g"]
    ).round(2)
 
    print_flagged(
        flagged,
        ["sugars_100g", "carbs_100g", "excess"],
        "sugar > carbs"
    )
    return len(flagged)
 
 
# -- Check 3: Saturated fat cannot exceed total fat ---------------------------
 
def check_saturated_vs_total_fat(df):
    print_section("CHECK 3 — Saturated fat cannot exceed total fat")
    print("  Rule: saturated_fat_100g must be <= fat_100g")
 
    both_present = df[
        df["saturated_fat_100g"].notna() & df["fat_100g"].notna()
    ]
    flagged = both_present[
        both_present["saturated_fat_100g"] > both_present["fat_100g"]
    ].copy()
    flagged["excess"] = (
        flagged["saturated_fat_100g"] - flagged["fat_100g"]
    ).round(2)
 
    print_flagged(
        flagged,
        ["saturated_fat_100g", "fat_100g", "excess"],
        "saturated fat > total fat"
    )
    return len(flagged)
 
 
# -- Check 4: Pack size sanity ------------------------------------------------
 
def parse_quantity_ml(text):
    """
    Extract numeric value and unit from quantity field.
    Returns (value, unit) or (None, None) if unparseable.
    Examples: '500ml' -> (500, 'ml')
              '6x45g' -> (270, 'g')   # multiplies pack counts
              '1L'    -> (1000, 'ml')
              '400g'  -> (400, 'g')
    """
    if not isinstance(text, str) or text.strip() == "":
        return None, None
 
    text = text.lower().strip()
 
    # Handle multipack: 6x45g -> 270g
    multi = re.match(r"(\d+)\s*x\s*([\d.]+)\s*(g|ml|l|kg|cl)", text)
    if multi:
        count = float(multi.group(1))
        value = float(multi.group(2))
        unit  = multi.group(3)
        total = count * value
        if unit == "kg":
            return total * 1000, "g"
        if unit == "l":
            return total * 1000, "ml"
        if unit == "cl":
            return total * 10, "ml"
        return total, unit
 
    # Single value
    single = re.search(r"([\d.]+)\s*(g|ml|l|kg|cl)\b", text)
    if single:
        value = float(single.group(1))
        unit  = single.group(2)
        if unit == "kg":
            return value * 1000, "g"
        if unit == "l":
            return value * 1000, "ml"
        if unit == "cl":
            return value * 10, "ml"
        return value, unit
 
    return None, None
 
 
def check_pack_sizes(df):
    print_section("CHECK 4 — Pack size sanity")
    print("  Parsing quantity field for obviously wrong pack sizes\n")
 
    df = df.copy()
    df[["qty_value", "qty_unit"]] = df["quantity"].apply(
        lambda x: pd.Series(parse_quantity_ml(x))
    )
 
    parsed = df[df["qty_value"].notna()]
    unparseable = df[df["qty_value"].isna() & df["quantity"].notna()
                     & (df["quantity"].str.strip() != "")]
 
    print(f"  Parsed:      {len(parsed)} of {len(df)} rows")
    print(f"  Unparseable: {len(unparseable)} rows")
 
    flagged = []
 
    # Beverages: liquid expected, flag if > 5000ml or solid unit
    bevs = parsed[parsed["query_category"] == "beverages"]
    bev_flags = bevs[
        ((bevs["qty_unit"] == "ml") & (bevs["qty_value"] > 5000)) |
        ((bevs["qty_unit"] == "g")  & (bevs["qty_value"] > 5000)) |
        ((bevs["qty_unit"] == "g")  & (bevs["qty_value"] < 5))
    ]
    if len(bev_flags):
        print(f"\n  Beverages with suspicious pack size ({len(bev_flags)}):")
        print("  " + bev_flags[
            ["product_name", "brands", "quantity", "qty_value", "qty_unit"]
        ].to_string().replace("\n", "\n  "))
    else:
        print(f"  Beverages pack sizes — PASS")
    flagged.append(bev_flags)
 
    # Solids: flag if < 5g (probably a serving size error) or > 10000g
    solids = parsed[
        (parsed["query_category"].isin(["snacks", "cereals"])) &
        (parsed["qty_unit"] == "g")
    ]
    solid_flags = solids[
        (solids["qty_value"] < 5) |
        (solids["qty_value"] > 10000)
    ]
    if len(solid_flags):
        print(f"\n  Snacks/cereals with suspicious pack size ({len(solid_flags)}):")
        print("  " + solid_flags[
            ["product_name", "brands", "quantity", "qty_value", "qty_unit"]
        ].to_string().replace("\n", "\n  "))
    else:
        print(f"  Snacks/cereals pack sizes — PASS")
    flagged.append(solid_flags)
 
    total = sum(len(f) for f in flagged)
    print(f"\n  Total flagged: {total}")
 
    # Show unparseable for awareness
    if len(unparseable):
        print(f"\n  Unparseable quantity values (not flagged, for awareness):")
        print("  " + unparseable[
            ["product_name", "brands", "quantity"]
        ].head(10).to_string().replace("\n", "\n  "))
 
    return total
 
 
# -- Run all checks -----------------------------------------------------------
 
def main():
    path = find_latest_clean(SAMPLE_DIR)
    df   = pd.read_csv(path, encoding="utf-8-sig")
 
    print(f"\nFunctional Food Radar - reality_checks.py")
    print(f"Input: {os.path.basename(path)}")
    print(f"Rows:  {len(df)}")
 
    total1 = check_calories(df)
    total2 = check_sugar_vs_carbs(df)
    total3 = check_saturated_vs_total_fat(df)
    total4 = check_pack_sizes(df)
 
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Check 1 — Calorie plausibility:      {total1} flag(s)")
    print(f"  Check 2 — Sugar vs carbs:            {total2} flag(s)")
    print(f"  Check 3 — Saturated vs total fat:    {total3} flag(s)")
    print(f"  Check 4 — Pack size sanity:          {total4} flag(s)")
    print(f"  Total flags: {total1 + total2 + total3 + total4}")
    print(f"\n  Add findings to docs/DATA_OBSERVATIONS.md as OBS-007\n")
 
 
if __name__ == "__main__":
    main()