"""
clean.py
--------
Cleans the raw CSV produced by ingest.py and outputs an analysis-ready CSV.
 
Cleaning decisions based on data exploration (18 May 2026):
    - 300 rows, 22 columns
    - 80% FR ingredients, 10% EN, 9% OTHER, 1% BOTH
    - Nulls in nutritional cols only (8-21%), zero nulls in text fields
    - energy_kcal max was 3833 (physically impossible - data error)
    - HTML entities present: &quot; &lt; &gt;
    - Whitespace artifacts: \r\n in ingredients text
 
What this script does:
    1.  Load latest sample_all_*.csv automatically
    2.  Drop exact duplicate barcodes
    3.  Drop rows with no product name AND no ingredients
    4.  Clean HTML entities from text fields
    5.  Clean whitespace artifacts (\r\n etc.)
    6.  Detect language of ingredients_text (FR / EN / BOTH / OTHER / UNKNOWN)
    7.  Normalise text fields (strip, collapse whitespace)
    8.  Lowercase brands for consistent Power BI grouping
    9.  Coerce nutritional columns to numeric
    10. Cap physically impossible nutritional outliers (set to NaN)
    11. Add missing value flag columns (boolean) - we flag, never impute
    12. Normalise nutriscore_grade to uppercase
    13. Convert Unix timestamps to readable dates
    14. Add completeness_score (0-100) - proxy for agentic readiness
    15. Add nullable cluster_label column (v2 stub)
    16. Save clean CSV to data/sample/
 
Usage:
    python pipeline/clean.py
 
Input:
    data/sample/sample_all_<timestamp>.csv   (latest file auto-detected)
 
Output:
    data/sample/clean_<timestamp>.csv
"""
 
import pandas as pd
import os
import re
import html
from datetime import datetime
 
# -- Paths --------------------------------------------------------------------
 
ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(ROOT, "data", "sample")
 
# -- Language detection -------------------------------------------------------
# Keyword-based detection - no external dependencies.
# Covers EN/FR which is ~90% of our data (confirmed by check_languages.py).
# OTHER covers Bulgarian, German, Spanish, Arabic etc. - valid nutritional
# data, excluded from NLP analysis in v1 but retained in dataset.
 
FRENCH_MARKERS = [
    "farine", "sucre", "huile", "beurre", "lait", "eau", "sel",
    "arome", "emulsifiant", "colorant",
    "conservateur", "acidifiant", "epaississant",
    "sirop", "poudre", "extrait", "naturel", "vegetal",
    "contient", "peut contenir", "ingredients", "farine de ble",
    "huile de palme", "lecithine", "amidon",
]
 
ENGLISH_MARKERS = [
    "flour", "sugar", "oil", "butter", "milk", "water", "salt",
    "flavour", "flavor", "emulsifier", "colouring", "coloring",
    "preservative", "thickener", "syrup", "powder", "extract",
    "natural", "contains", "may contain", "wheat flour",
    "palm oil", "lecithin", "starch",
]
 
 
def detect_language(text):
    """
    Returns 'FR', 'EN', 'BOTH', 'OTHER', or 'UNKNOWN'.
    BOTH = bilingual packaging (Switzerland, Belgium, Canada).
    OTHER = language with no EN/FR markers (retained, excluded from NLP v1).
    """
    if not isinstance(text, str) or len(text.strip()) < 10:
        return "UNKNOWN"
 
    text_lower = text.lower()
    fr = any(kw in text_lower for kw in FRENCH_MARKERS)
    en = any(kw in text_lower for kw in ENGLISH_MARKERS)
 
    if fr and en:
        return "BOTH"
    if fr:
        return "FR"
    if en:
        return "EN"
    return "OTHER"
 
 
# -- Nutritional columns ------------------------------------------------------
 
NUTRIMENT_COLS = [
    "energy_kcal",
    "fat_100g",
    "saturated_fat_100g",
    "carbs_100g",
    "sugars_100g",
    "fiber_100g",
    "protein_100g",
    "salt_100g",
]
 
# Physically impossible values per 100g
# energy_kcal max was 3833 in our sample (pure fat = ~900 kcal max)
NUTRIMENT_CAPS = {
    "energy_kcal":        900,
    "fat_100g":           100,
    "saturated_fat_100g": 100,
    "carbs_100g":         100,
    "sugars_100g":        100,
    "fiber_100g":         100,
    "protein_100g":       100,
    "salt_100g":          100,
}
 
# Fields used to calculate completeness score
# These are the fields an AI shopping agent would query
COMPLETENESS_COLS = [
    "product_name",
    "brands",
    "ingredients_text",
    "energy_kcal",
    "fat_100g",
    "carbs_100g",
    "sugars_100g",
    "protein_100g",
    "salt_100g",
    "nutriscore_grade",
    "nova_group",
]
 
 
# -- Helpers ------------------------------------------------------------------
 
def find_latest_sample(sample_dir):
    """Auto-detect the most recently created sample_all_*.csv file."""
    files = [
        f for f in os.listdir(sample_dir)
        if f.startswith("sample_all_") and f.endswith(".csv")
    ]
    if not files:
        raise FileNotFoundError(
            f"No sample_all_*.csv found in {sample_dir}. "
            "Run ingest.py first."
        )
    files.sort(reverse=True)
    return os.path.join(sample_dir, files[0])
 
 
def clean_text(text):
    """
    1. Decode HTML entities  (&quot; -> "  &lt; -> <  etc.)
    2. Replace \r\n and \n with a single space
    3. Collapse multiple spaces into one
    4. Strip leading/trailing whitespace
    """
    if not isinstance(text, str):
        return text
    text = html.unescape(text)
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text
 
 
def cap_outliers(df):
    """Set physically impossible nutritional values to NaN and report them."""
    total_capped = 0
    for col, cap in NUTRIMENT_CAPS.items():
        if col in df.columns:
            mask = df[col] > cap
            count = mask.sum()
            if count > 0:
                print(f"    Capped {count} outlier(s) in {col} "
                      f"(max was {df.loc[mask, col].max():.1f}, cap={cap})")
                df.loc[mask, col] = None
                total_capped += count
    if total_capped == 0:
        print(f"    No outliers found")
    return df
 
 
def add_missing_flags(df):
    """
    Add boolean flag columns for missing nutritional values.
    We FLAG rather than IMPUTE - imputation would corrupt NLP analysis
    and mislead v2 clustering. Flags are useful as a Power BI dimension.
    """
    for col in NUTRIMENT_COLS:
        if col in df.columns:
            df[f"{col}_missing"] = df[col].isnull()
    return df
 
 
def completeness_score(row):
    """
    Score a product 0-100 based on key field population.
    Rationale: proxy for AI/agentic shopping readiness.
    A brand with complete structured data wins in a machine-queried world.
    See docs/ADR.md for full rationale.
    """
    filled = sum(
        1 for col in COMPLETENESS_COLS
        if col in row.index
        and row[col] is not None
        and str(row[col]).strip() not in ("", "nan", "NaN", "none", "None")
    )
    return round((filled / len(COMPLETENESS_COLS)) * 100)
 
 
# -- Main cleaning pipeline ---------------------------------------------------
 
def clean(input_path):
 
    print(f"\n  Input file: {os.path.basename(input_path)}")
    df = pd.read_csv(input_path, encoding="utf-8-sig")
    print(f"  Rows on load: {len(df)}")
 
    # Step 1: Drop exact duplicate barcodes
    before = len(df)
    df = df.drop_duplicates(subset=["barcode"])
    dropped = before - len(df)
    print(f"\n  Step 1  - Duplicates: dropped {dropped} duplicate barcode(s)")
 
    # Step 2: Drop rows with no product name AND no ingredients
    before = len(df)
    df = df[~(df["product_name"].isnull() & df["ingredients_text"].isnull())]
    print(f"  Step 2  - Empty rows: dropped {before - len(df)} "
          f"(no name + no ingredients)")
 
    # Step 3: Clean HTML entities and whitespace artifacts
    for col in ["product_name", "brands", "ingredients_text",
                "off_categories", "packaging"]:
        if col in df.columns:
            df[col] = df[col].apply(clean_text)
    print(f"  Step 3  - HTML entities, whitespace, and quantity commas cleaned")

    # Normalise European decimal commas in quantity field
    # e.g. "1,15 L" -> "1.15 L" (prevents multipack parser misreading)
    if "quantity" in df.columns:
        df["quantity"] = df["quantity"].str.replace(
            r"(\d),(\d)", r"\1.\2", regex=True
        )

 
    # Step 4: Normalise brands
    df["brands"] = (
        df["brands"]
        .str.lower()
        .str.strip()
        .str.strip(",")
    )
    print(f"  Step 4  - Brands normalised (lowercase, stripped)")
 
    # Step 5: Detect ingredient language
    df["ingredients_lang"] = df["ingredients_text"].apply(detect_language)
    lang_counts = df["ingredients_lang"].value_counts().to_dict()
    print(f"  Step 5  - Language detection: {lang_counts}")
 
    # Step 6: Coerce nutritional columns to numeric
    for col in NUTRIMENT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    print(f"  Step 6  - Nutritional columns coerced to numeric")
 
    # Step 7: Cap outliers
    print(f"  Step 7  - Capping outliers:")
    df = cap_outliers(df)
 
    # Step 8: Add missing value flags
    df = add_missing_flags(df)
    print(f"  Step 8  - Missing value flags added "
          f"({len(NUTRIMENT_COLS)} flag columns)")
 
    # Step 9: Normalise nutriscore to uppercase
    df["nutriscore_grade"] = (
        df["nutriscore_grade"]
        .astype(str)
        .str.upper()
        .str.strip()
        .replace("NAN", None)
    )
    print(f"  Step 9  - Nutriscore normalised to uppercase")
 
    # Step 10: Convert Unix timestamps to readable dates
    for col in ["created_t", "last_modified_t"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], unit="s", errors="coerce")
    print(f"  Step 10 - Timestamps converted to datetime")
 
    # Step 11: Add completeness score
    df["completeness_score"] = df.apply(completeness_score, axis=1)
    avg = df["completeness_score"].mean()
    print(f"  Step 11 - Completeness score added (avg: {avg:.1f}/100)")

    # Step 11b: Extract primary country from pipe-separated countries field
    df["primary_country"] = df["countries"].apply(
        lambda x: str(x).split("|")[0]
                         .replace("en:", "")
                         .replace("-", " ")
                         .title()
                  if isinstance(x, str) and x.strip() not in ("", "nan")
                  else "Unknown"
    )
    print(f"  Step 11b- Primary country extracted")
    print(f"            Top countries: "
          f"{df['primary_country'].value_counts().head(5).to_dict()}")
 
    # Step 12: Flag rows eligible for NLP analysis (EN and FR only)
    # OTHER/UNKNOWN rows retained for nutritional analysis but excluded
    # from Option A ingredient flagging.
    # BOTH = bilingual packaging, treated as eligible.
    # Coverage: ~84% of rows based on 18 May 2026 sample.
    # See docs/DATA_OBSERVATIONS.md OBS-001 and OBS-008.
    df["nlp_eligible"] = df["ingredients_lang"].isin(["EN", "FR", "BOTH"])
    eligible = df["nlp_eligible"].sum()
    print(f"  Step 12 - NLP eligible: {eligible} of {len(df)} rows "
          f"({eligible/len(df)*100:.0f}%)")

    # Step 13: Add nullable cluster_label (v2 stub)
    # Intentionally empty in v1. K-Means (Option B) will populate this.
    # Column exists now so SQLite schema and Power BI model don't break.
    # See docs/ADR.md.
    if "cluster_label" not in df.columns:
        df["cluster_label"] = None
    print(f"  Step 13 - cluster_label column added (null, v2 stub)")

 
    return df
 
 
# -- Run ----------------------------------------------------------------------
 
def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\nFunctional Food Radar - clean.py")
    print(f"Run timestamp: {timestamp}")
 
    input_path = find_latest_sample(SAMPLE_DIR)
    df = clean(input_path)
 
    # Summary
    print(f"\n  -- Summary --------------------------------------------------")
    print(f"  Rows:    {len(df)}")
    print(f"  Columns: {len(df.columns)}")
 
    print(f"\n  Nulls in nutritional columns (after capping):")
    for col in NUTRIMENT_COLS:
        n   = df[col].isnull().sum()
        pct = (n / len(df)) * 100
        print(f"    {col:<25} {n:>3} missing ({pct:.0f}%)")
 
    print(f"\n  Language distribution:")
    print("  " + df["ingredients_lang"].value_counts().to_string()
          .replace("\n", "\n  "))
 
    print(f"\n  Nutriscore distribution:")
    print("  " + df["nutriscore_grade"].value_counts().to_string()
          .replace("\n", "\n  "))
 
    print(f"\n  Completeness score:")
    print("  " + df["completeness_score"].describe().round(1).to_string()
          .replace("\n", "\n  "))
 
    print(f"\n  Low completeness products (score < 50):")
    low = df[df["completeness_score"] < 50][
        ["product_name", "brands", "completeness_score"]
    ]
    if len(low):
        print("  " + low.to_string().replace("\n", "\n  "))
    else:
        print("  None - all products score >= 50")
 
    # Save
    output_filename = f"clean_{timestamp}.csv"
    output_path     = os.path.join(SAMPLE_DIR, output_filename)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n  Saved -> {output_filename}")
    print(f"  ({len(df)} rows, {len(df.columns)} columns)\n")
 
 
if __name__ == "__main__":
    main()
