"""
analyze.py
----------
Option A — Rule-based NLP ingredient flagging.
Version 2 — implements ADR-010 architectural pivot.

WHAT CHANGED FROM v1:
    Component B (claim inflation) and Component C (contradiction gap)
    are NO LONGER computed from ingredient text.
    They will be fed by Azure Vision output in v3 (vision_extract.py).

    The score produced here is renamed health_wash_score_v1 and measures
    ONLY Component A: UPF reality (what the product actually contains).

    Functional claims are still DETECTED and stored as columns —
    they feed the v3 join and the half-truth detectors below.

WHAT IS NEW:
    Four half-truth detection columns (from practitioner feedback):
    - ht_sugar_loophole:     "no added sugar" claim but high sugar content
    - ht_protein_masks_fat:  protein claim but high calories or sat fat
    - ht_fibre_distraction:  fibre claim on NOVA 4 with high sugar
    - ht_vegan_calorie_trap: plant milk with fortification claim, high kcal

v3 bridge:
    health_wash_score_v1 (UPF reality) + vision claims (Azure)
    => health_wash_score_v3 (final gap metric) via merge_scores.py

Usage:
    python pipeline/analyze.py

Input:
    data/sample/clean_<timestamp>.csv   (latest file auto-detected)
    OR data/sample/bulk_clean_<timestamp>.csv

Output:
    data/sample/analyzed_<timestamp>.csv
"""

import pandas as pd
import os
import re
from datetime import datetime
from collections import Counter

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(ROOT, "data", "sample")


# ── Ultra-processed ingredient markers ───────────────────────────────────────
# These feed Component A only — UPF REALITY.
# Do NOT add claim language here. Claims come from Azure Vision in v3.
# See ADR-010.

ULTRA_PROCESSED_MARKERS = [
    # Artificial sweeteners
    ("aspartame",              "artificial_sweetener", 3),
    ("acesulfame",             "artificial_sweetener", 3),
    ("saccharin",              "artificial_sweetener", 3),
    ("sucralose",              "artificial_sweetener", 3),
    ("cyclamate",              "artificial_sweetener", 3),
    ("stevia",                 "sweetener_natural",    1),
    ("steviol",                "sweetener_natural",    1),
    ("maltitol",               "polyol_sweetener",     2),
    ("sorbitol",               "polyol_sweetener",     2),
    ("xylitol",                "polyol_sweetener",     2),
    ("erythritol",             "polyol_sweetener",     1),
    # Emulsifiers
    ("lecithin",               "emulsifier",           1),
    ("lecithine",              "emulsifier",           1),
    ("mono- and diglycerides", "emulsifier",           2),
    ("monoglycerides",         "emulsifier",           2),
    ("diglycerides",           "emulsifier",           2),
    ("carrageenan",            "emulsifier_concern",   3),
    ("carraghenane",           "emulsifier_concern",   3),
    ("xanthan",                "thickener",            2),
    ("xanthane",               "thickener",            2),
    ("guar",                   "thickener",            1),
    ("carboxymethyl",          "thickener",            2),
    ("pectin",                 "thickener",            1),
    ("pectine",                "thickener",            1),
    # Preservatives
    ("sodium benzoate",        "preservative",         2),
    ("benzoate de sodium",     "preservative",         2),
    ("potassium sorbate",      "preservative",         2),
    ("sorbate de potassium",   "preservative",         2),
    ("sodium nitrite",         "preservative",         3),
    ("nitrite de sodium",      "preservative",         3),
    ("bha",                    "preservative",         3),
    ("bht",                    "preservative",         3),
    ("tbhq",                   "preservative",         3),
    # Flavourings
    ("artificial flavour",     "artificial_flavour",   3),
    ("artificial flavor",      "artificial_flavour",   3),
    ("natural flavour",        "added_flavour",        2),
    ("natural flavor",         "added_flavour",        2),
    ("arome naturel",          "added_flavour",        2),
    ("arome artificiel",       "artificial_flavour",   3),
    ("arome",                  "added_flavour",        1),
    ("flavouring",             "added_flavour",        1),
    ("flavoring",              "added_flavour",        1),
    # Glucose syrups and refined sugars
    ("glucose syrup",          "glucose_syrup",        3),
    ("sirop de glucose",       "glucose_syrup",        3),
    ("high fructose",          "glucose_syrup",        3),
    ("corn syrup",             "glucose_syrup",        3),
    ("dextrose",               "refined_sugar",        2),
    ("maltodextrin",           "maltodextrin",         3),
    ("maltodextrine",          "maltodextrin",         3),
    # Refined starches
    ("modified starch",        "modified_starch",      2),
    ("amidon modifie",         "modified_starch",      2),
    ("amidon",                 "starch",               1),
    ("starch",                 "starch",               1),
    # Industrial fats
    ("palm oil",               "palm_oil",             2),
    ("huile de palme",         "palm_oil",             2),
    ("partially hydrogenated", "trans_fat",            3),
    ("interesterified",        "industrial_fat",       2),
    # Raising agents
    ("sodium carbonate",       "raising_agent",        1),
    ("carbonate de sodium",    "raising_agent",        1),
    ("ammonium carbonate",     "raising_agent",        1),
    ("sodium bicarbonate",     "raising_agent",        1),
    ("bicarbonate de sodium",  "raising_agent",        1),
    # Colours
    ("caramel colour",         "artificial_colour",    2),
    ("caramel color",          "artificial_colour",    2),
    ("tartrazine",             "artificial_colour",    3),
    ("sunset yellow",          "artificial_colour",    3),
    ("brilliant blue",         "artificial_colour",    3),
    ("allura red",             "artificial_colour",    3),
    ("colorant",               "colour",               1),
    # Acid regulators
    ("phosphoric acid",        "acid_regulator",       2),
    ("acide phosphorique",     "acid_regulator",       2),
    ("citric acid",            "acid_regulator",       1),
    ("acide citrique",         "acid_regulator",       1),
]

# ── E-number markers ──────────────────────────────────────────────────────────

E_NUMBER_MARKERS = [
    ("e950",  "artificial_sweetener", 3),
    ("e951",  "artificial_sweetener", 3),
    ("e952",  "artificial_sweetener", 3),
    ("e954",  "artificial_sweetener", 3),
    ("e955",  "artificial_sweetener", 3),
    ("e960",  "sweetener_natural",    1),
    ("e407",  "emulsifier_concern",   3),
    ("e322",  "emulsifier",           1),
    ("e471",  "emulsifier",           2),
    ("e415",  "thickener",            2),
    ("e412",  "thickener",            1),
    ("e150d", "artificial_colour",    2),
    ("e250",  "preservative",         3),
    ("e251",  "preservative",         3),
    ("e211",  "preservative",         2),
    ("e202",  "preservative",         2),
    ("e338",  "acid_regulator",       2),
    ("e330",  "acid_regulator",       1),
    ("e621",  "flavour_enhancer",     2),
]

# ── Functional claim markers ──────────────────────────────────────────────────
# DETECTED AND STORED but NOT used in scoring (ADR-010).
# Purpose: v3 join key, half-truth detection, Power BI filtering.
# Claims on front-of-pack will be extracted by Azure Vision in v3.

FUNCTIONAL_CLAIM_MARKERS = [
    # Protein — require explicit claim context, not bare ingredient
    ("high protein",          "protein_claim"),
    ("high-protein",          "protein_claim"),
    ("protein bar",           "protein_claim"),
    ("protein shake",         "protein_claim"),
    ("protein powder",        "protein_claim"),
    ("whey protein",          "protein_claim"),
    ("pea protein",           "protein_claim"),
    ("soy protein isolate",   "protein_claim"),
    ("plant protein",         "protein_claim"),
    ("added protein",         "protein_claim"),
    ("riche en proteines",    "protein_claim"),
    ("proteines ajoutees",    "protein_claim"),
    ("source de proteines",   "protein_claim"),
    ("proteinangereichert",   "protein_claim"),   # DE v1.5
    ("proteinquelle",         "protein_claim"),   # DE v1.5
    # Probiotic
    ("probiotic",             "probiotic_claim"),
    ("probiotique",           "probiotic_claim"),
    ("lactobacillus",         "probiotic_claim"),
    ("bifidobacterium",       "probiotic_claim"),
    ("bifidus",               "probiotic_claim"),
    ("live cultures",         "probiotic_claim"),
    ("ferments lactiques",    "probiotic_claim"),
    # Prebiotic / fibre
    ("prebiotic",             "prebiotic_claim"),
    ("prebiotique",           "prebiotic_claim"),
    ("inulin de chicoree",    "prebiotic_claim"),
    ("extrait de chicoree",   "prebiotic_claim"),
    ("chicory root",          "prebiotic_claim"),
    ("source de fibres",      "fibre_claim"),
    ("source of fibre",       "fibre_claim"),
    ("source of fiber",       "fibre_claim"),
    ("riche en fibres",       "fibre_claim"),
    ("high in fibre",         "fibre_claim"),
    ("ballaststoffquelle",    "fibre_claim"),      # DE v1.5
    # Vitamins / fortification
    ("vitamin",               "fortification_claim"),
    ("vitamine",              "fortification_claim"),
    ("calcium",               "fortification_claim"),
    ("magnesium",             "fortification_claim"),
    ("zinc",                  "fortification_claim"),
    ("omega-3",               "fortification_claim"),
    ("omega 3",               "fortification_claim"),
    ("collagen",              "fortification_claim"),
    ("collagene",             "fortification_claim"),
    ("germe de ble",          "fortification_claim"),
    ("wheat germ",            "fortification_claim"),
    # Adaptogens — require extract context (not bare colorant ingredient)
    ("ashwagandha",           "adaptogen_claim"),
    ("maca",                  "adaptogen_claim"),
    ("turmeric extract",      "adaptogen_claim"),
    ("curcumin extract",      "adaptogen_claim"),
    ("extrait de curcuma",    "adaptogen_claim"),
    ("ginseng",               "adaptogen_claim"),
    ("matcha",                "adaptogen_claim"),
    ("spirulina",             "adaptogen_claim"),
    ("spiruline",             "adaptogen_claim"),
    ("chlorella",             "adaptogen_claim"),
    ("moringa",               "adaptogen_claim"),
    # Keto
    ("keto",                  "keto_claim"),
    ("ketogenic",             "keto_claim"),
    ("low carb",              "keto_claim"),
    ("low-carb",              "keto_claim"),
    # Energy — stored but excluded from scoring (ADR-010, OBS-017)
    ("caffeine",              "energy_claim"),
    ("cafeine",               "energy_claim"),
    ("guarana",               "energy_claim"),
    ("taurine",               "energy_claim"),
    ("creatine",              "energy_claim"),
    ("electrolyte",           "energy_claim"),
    # German v1.5 stubs
    ("proteinangereichert",   "protein_claim"),
    ("proteinquelle",         "protein_claim"),
    ("ballaststoffquelle",    "fibre_claim"),

    # ── NEW: Vegan positioning ────────────────────────────────────────────────
    ("100% vegan",            "vegan_claim"),
    ("totally vegan",         "vegan_claim"),
    ("vegan",                 "vegan_claim"),
    ("vegane",                "vegan_claim"),
    ("végan",                 "vegan_claim"),

    # ── NEW: Organic / Bio ────────────────────────────────────────────────────
    ("bio",                   "organic_claim"),
    ("organic",               "organic_claim"),
    ("biologisch",            "organic_claim"),
    ("biologique",            "organic_claim"),
    ("100% bio",              "organic_claim"),

    # ── NEW: Dairy-free / plant-based ─────────────────────────────────────────
    ("no dairy",              "dairy_free_claim"),
    ("dairy free",            "dairy_free_claim"),
    ("dairy-free",            "dairy_free_claim"),
    ("no milk",               "dairy_free_claim"),
    ("plant-based",           "plant_based_claim"),
    ("plant based",           "plant_based_claim"),

    # ── NEW: Climate / environmental ──────────────────────────────────────────
    ("climate footprint",     "sustainability_halo"),
    ("carbon footprint",      "sustainability_halo"),
    ("carbon neutral",        "sustainability_halo"),
    ("net zero",              "sustainability_halo"),
    ("climate positive",      "sustainability_halo"),

    # ── NEW: Heritage ─────────────────────────────────────────────────────────
    ("the original",          "heritage_claim"),

    # ── NEW: GLP-1 adjacent ───────────────────────────────────────────────────
    ("low calorie",           "glp1_positioning"),
    ("weight management",     "glp1_positioning"),
]

# ── Negative claim markers ────────────────────────────────────────────────────

NEGATIVE_CLAIM_MARKERS = [
    ("no added sugar",        "no_added_sugar"),
    ("no sugar added",        "no_added_sugar"),
    ("sugar free",            "no_added_sugar"),
    ("sugar-free",            "no_added_sugar"),
    ("no lactose",            "no_lactose"),
    ("lactose free",          "no_lactose"),
    ("lactose-free",          "no_lactose"),
    ("no gluten",             "no_gluten"),
    ("gluten free",           "no_gluten"),
    ("gluten-free",           "no_gluten"),
    ("no preservatives",      "no_preservatives"),
    ("no artificial",         "no_artificial"),
    ("all natural",           "natural_claim"),
    ("100% natural",          "natural_claim"),
    ("clean label",           "clean_label"),
    ("no palm oil",           "no_palm_oil"),
    ("palm oil free",         "no_palm_oil"),
    ("non gmo",               "non_gmo"),
    ("non-gmo",               "non_gmo"),
    ("sans sucre ajoute",     "no_added_sugar"),
    ("sans sucres ajoutes",   "no_added_sugar"),
    ("sans sucre",            "no_added_sugar"),
    ("sans lactose",          "no_lactose"),
    ("sans gluten",           "no_gluten"),
    ("sans conservateur",     "no_preservatives"),
    ("sans additif",          "no_additives"),
    ("sans colorant",         "no_artificial"),
    ("naturel",               "natural_claim"),
    ("100% naturel",          "natural_claim"),
    ("sans huile de palme",   "no_palm_oil"),
    ("moins de sucre",        "reduced_sugar"),
    ("reduit en sucres",      "reduced_sugar"),
    ("ohne zuckerzusatz",     "no_added_sugar"),   # DE v1.5
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_latest_clean(sample_dir):
    files = [
        f for f in os.listdir(sample_dir)
        if (f.startswith("clean_") or f.startswith("bulk_clean_"))
        and f.endswith(".csv")
    ]
    if not files:
        raise FileNotFoundError(
            f"No clean_*.csv found in {sample_dir}. Run clean.py first."
        )
    files.sort(reverse=True)
    return os.path.join(sample_dir, files[0])


def flag_text(text, markers):
    """Scan lowercased text against markers. Returns list of matching tuples."""
    if not isinstance(text, str) or text.strip() == "":
        return []
    text_lower = text.lower()
    found = []
    seen_labels = set()
    for marker in markers:
        keyword = marker[0]
        label   = marker[1]
        if label in seen_labels:
            continue
        if len(keyword) < 5:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text_lower):
                found.append(marker)
                seen_labels.add(label)
        else:
            if keyword in text_lower:
                found.append(marker)
                seen_labels.add(label)
    return found


def flag_additives(additives_str, e_markers):
    """Scan pipe-separated additives_tags against E-number markers."""
    if not isinstance(additives_str, str) or additives_str.strip() == "":
        return []
    additives_lower = additives_str.lower()
    found = []
    seen_labels = set()
    for e_num, label, severity in e_markers:
        if label in seen_labels:
            continue
        if e_num in additives_lower:
            found.append((e_num, label, severity))
            seen_labels.add(label)
    return found


def strip_parenthetical_enrichment(text):
    """
    Strip parenthetical sub-lists before checking functional claims.
    Prevents 'enriched flour (niacin, riboflavin, folic acid...)' from
    triggering fortification_claim on mandatory US flour enrichment.
    Also strips colorant context phrases (OBS-019).
    See ADR-010 and DATA_OBSERVATIONS OBS-019.
    """
    if not isinstance(text, str):
        return text
    cleaned = re.sub(r'\([^)]*\)', ' ', text)
    color_phrases = [
        r'pour la couleur[\w\s]*',
        r'a pouvoir colorant[\w\s]*',
        r'colorant\s*:[\w\s]*',
        r'farbgebendes lebensmittel[\w\s]*',
        r'farbstoff\s*:[\w\s]*',
    ]
    for cp in color_phrases:
        cleaned = re.sub(cp, ' ', cleaned.lower())
    return cleaned


# ── Scoring ───────────────────────────────────────────────────────────────────

def compute_health_wash_score_v1(upf_flags):
    """
    Component A only: UPF reality (0-40 points).
    Severity-weighted count of ultra-processed markers in ingredient text.

    Components B and C (claim inflation + contradiction gap) will be
    added in merge_scores.py after Azure Vision extraction.
    See ADR-010.
    """
    if not upf_flags:
        return 0
    severity_total = sum(f[2] for f in upf_flags)
    return min(severity_total * 3, 40)


def classify_health_wash_v1(score):
    if score >= 30:
        return "HIGH UPF — strong ultra-processed markers"
    elif score >= 20:
        return "MEDIUM UPF — significant ultra-processed markers"
    elif score >= 10:
        return "LOW UPF — some ultra-processed markers"
    else:
        return "CLEAN — minimal ultra-processed markers"


# ── Half-truth detectors ──────────────────────────────────────────────────────

def detect_sugar_loophole(row):
    """
    HT-1: Natural sugar loophole.
    'No added sugar' claim but product has high actual sugar content.
    Examples: Innocent, Nakd, Emmi Energy Milk, fruit concentrates.
    """
    neg = str(row.get("negative_claims_found", "") or "")
    has_claim = "no_added_sugar" in neg or "reduced_sugar" in neg
    try:
        sugars = float(row.get("sugars_100g"))
    except (TypeError, ValueError):
        sugars = None
    return bool(has_claim and sugars is not None and sugars > 8)


def detect_protein_masks_fat(row):
    """
    HT-2: Protein claim masking high calories or saturated fat.
    Examples: Chiefs High Protein Puddings, Nature Valley Protein bars.
    """
    func = str(row.get("functional_claims_found", "") or "")
    if "protein_claim" not in func:
        return False
    try:
        kcal    = float(row.get("energy_kcal"))
        sat_fat = float(row.get("saturated_fat_100g"))
    except (TypeError, ValueError):
        kcal = None
        sat_fat = None
    if kcal is not None and kcal > 400:
        return True
    if sat_fat is not None and sat_fat > 5:
        return True
    return False


def detect_fibre_distraction(row):
    """
    HT-3: Fibre/whole grain claim distracting from NOVA 4 + high sugar.
    Examples: Belvita, Kellogg's Special K, Kellogg's All-Bran.
    """
    func = str(row.get("functional_claims_found", "") or "")
    if "fibre_claim" not in func and "prebiotic_claim" not in func:
        return False
    try:
        nova   = float(row.get("nova_group"))
        sugars = float(row.get("sugars_100g"))
    except (TypeError, ValueError):
        nova = None
        sugars = None
    return bool(nova == 4.0 and sugars is not None and sugars > 15)


def detect_vegan_calorie_trap(row):
    """
    HT-4: Plant milk with fortification claims but calorie-dense.
    Threshold: >60 kcal/100ml (whole dairy milk benchmark).
    Examples: Oatly, some Alpro products.
    """
    func = str(row.get("functional_claims_found", "") or "")
    if "fortification_claim" not in func:
        return False
    off_cats = str(row.get("off_categories", "") or "").lower()
    is_plant_milk = any(kw in off_cats for kw in [
        "plant-based", "oat-milk", "almond-milk", "soy-milk",
        "coconut-milk", "rice-milk", "hafer", "mandel", "avoine",
        "amande", "soja", "oat drink", "almond drink",
    ])
    if not is_plant_milk:
        return False
    try:
        kcal = float(row.get("energy_kcal"))
    except (TypeError, ValueError):
        kcal = None
    return bool(kcal is not None and kcal > 60)


# ── Main analysis pipeline ────────────────────────────────────────────────────

def analyze(input_path):
    print(f"\n  Input file: {os.path.basename(input_path)}")
    df = pd.read_csv(input_path, encoding="utf-8-sig", low_memory=False,
                     dtype={"barcode": str})
    print(f"  Rows on load: {len(df):,}")

    eligible   = df[df["nlp_eligible"] == True].copy()
    ineligible = df[df["nlp_eligible"] != True].copy()
    print(f"\n  Step 1  - NLP eligible: {len(eligible):,} rows")
    print(f"            NLP excluded: {len(ineligible):,} rows")

    # Step 2: UPF markers — Component A
    print(f"\n  Step 2  - Flagging UPF markers (Component A)...")
    eligible["_upf_flags"] = eligible["ingredients_text"].apply(
        lambda x: flag_text(x, ULTRA_PROCESSED_MARKERS)
    )
    eligible["upf_marker_count"]    = eligible["_upf_flags"].apply(len)
    eligible["upf_markers_found"]   = eligible["_upf_flags"].apply(
        lambda f: "|".join(x[1] for x in f) if f else ""
    )
    eligible["upf_max_severity"]    = eligible["_upf_flags"].apply(
        lambda f: max((x[2] for x in f), default=0)
    )
    eligible["has_ultra_processed"] = eligible["upf_marker_count"] > 0
    n = eligible["has_ultra_processed"].sum()
    print(f"            {n:,} of {len(eligible):,} ({n/len(eligible)*100:.0f}%) have UPF markers")

    # Step 3: E-numbers
    print(f"\n  Step 3  - Cross-checking E-numbers...")
    eligible["_e_flags"] = eligible["additives_tags"].apply(
        lambda x: flag_additives(x, E_NUMBER_MARKERS)
    )
    eligible["e_number_count"]  = eligible["_e_flags"].apply(len)
    eligible["e_numbers_found"] = eligible["_e_flags"].apply(
        lambda f: "|".join(x[0] for x in f) if f else ""
    )
    sw_kw = [m for m in ULTRA_PROCESSED_MARKERS if m[1] == "artificial_sweetener"]
    eligible["has_artificial_sweetener"] = eligible.apply(
        lambda row: (
            any(f[1] == "artificial_sweetener" for f in row["_e_flags"]) or
            bool(flag_text(row["ingredients_text"], sw_kw))
        ), axis=1
    )
    e_n  = (eligible["e_number_count"] > 0).sum()
    sw_n = eligible["has_artificial_sweetener"].sum()
    print(f"            {e_n:,} products have flagged E-numbers")
    print(f"            {sw_n:,} products contain artificial sweeteners")

    # Step 4: Functional claims — stored for v3, NOT scored
    print(f"\n  Step 4  - Detecting functional claims (stored for v3, NOT scored)...")
    eligible["_claim_flags"] = eligible.apply(
        lambda row: flag_text(
            strip_parenthetical_enrichment(str(row["ingredients_text"])) +
            " " + str(row["product_name"]),
            FUNCTIONAL_CLAIM_MARKERS
        ), axis=1
    )
    eligible["functional_claim_count"]  = eligible["_claim_flags"].apply(len)
    eligible["functional_claims_found"] = eligible["_claim_flags"].apply(
        lambda f: "|".join(x[1] for x in f) if f else ""
    )
    claim_n = (eligible["functional_claim_count"] > 0).sum()
    print(f"            {claim_n:,} products have detectable claim language")
    all_claims = []
    for f in eligible["_claim_flags"]:
        all_claims.extend(x[1] for x in f)
    if all_claims:
        print(f"            Top claim categories:")
        for claim, count in Counter(all_claims).most_common(8):
            print(f"              {claim:<30} {count:,}")

    # Step 5: Negative claims — stored for v3
    print(f"\n  Step 5  - Detecting negative claims (stored for v3)...")
    eligible["_neg_flags"] = eligible.apply(
        lambda row: flag_text(
            str(row["product_name"]) + " " + str(row.get("labels", "")),
            NEGATIVE_CLAIM_MARKERS
        ), axis=1
    )
    eligible["negative_claim_count"]  = eligible["_neg_flags"].apply(len)
    eligible["negative_claims_found"] = eligible["_neg_flags"].apply(
        lambda f: "|".join(x[1] for x in f) if f else ""
    )
    neg_n = (eligible["negative_claim_count"] > 0).sum()
    print(f"            {neg_n:,} products have negative claim language")

    # Step 6: health_wash_score_v1 — Component A only
    print(f"\n  Step 6  - Computing health_wash_score_v1 (UPF reality, Component A only)...")
    eligible["health_wash_score_v1"]    = eligible["_upf_flags"].apply(
        compute_health_wash_score_v1
    )
    eligible["health_wash_category_v1"] = eligible["health_wash_score_v1"].apply(
        classify_health_wash_v1
    )
    # v3 placeholders — populated by merge_scores.py
    eligible["health_wash_score_v3"]    = None
    eligible["health_wash_category_v3"] = None
    eligible["v3_claims_found"]         = None

    dist = eligible["health_wash_category_v1"].value_counts()
    print(f"            Distribution:")
    for cat, n in dist.items():
        print(f"              {cat:<45} {n:,}")

    # Step 7: Half-truth detection
    print(f"\n  Step 7  - Half-truth pattern detection...")
    eligible["ht_sugar_loophole"]     = eligible.apply(detect_sugar_loophole,    axis=1)
    eligible["ht_protein_masks_fat"]  = eligible.apply(detect_protein_masks_fat, axis=1)
    eligible["ht_fibre_distraction"]  = eligible.apply(detect_fibre_distraction, axis=1)
    eligible["ht_vegan_calorie_trap"] = eligible.apply(detect_vegan_calorie_trap, axis=1)
    print(f"            HT-1 sugar loophole:       {eligible['ht_sugar_loophole'].sum():,}")
    print(f"            HT-2 protein masks fat:    {eligible['ht_protein_masks_fat'].sum():,}")
    print(f"            HT-3 fibre distraction:    {eligible['ht_fibre_distraction'].sum():,}")
    print(f"            HT-4 vegan calorie trap:   {eligible['ht_vegan_calorie_trap'].sum():,}")

    # Step 8: Clean up, reattach ineligible rows
    drop_cols = ["_upf_flags", "_e_flags", "_claim_flags", "_neg_flags"]
    eligible  = eligible.drop(columns=[c for c in drop_cols if c in eligible.columns])
    nlp_cols  = [
        "upf_marker_count", "upf_markers_found", "upf_max_severity",
        "has_ultra_processed", "e_number_count", "e_numbers_found",
        "has_artificial_sweetener", "functional_claim_count",
        "functional_claims_found", "negative_claim_count",
        "negative_claims_found", "health_wash_score_v1",
        "health_wash_category_v1", "health_wash_score_v3",
        "health_wash_category_v3", "v3_claims_found",
        "ht_sugar_loophole", "ht_protein_masks_fat",
        "ht_fibre_distraction", "ht_vegan_calorie_trap",
    ]
    for col in nlp_cols:
        if col not in ineligible.columns:
            ineligible[col] = None

    df_out = pd.concat([eligible, ineligible], ignore_index=True)
    df_out = df_out.sort_values("barcode").reset_index(drop=True)
    return df_out


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\nFunctional Food Radar - analyze.py v2 (ADR-010)")
    print(f"Run timestamp: {timestamp}")
    print(f"Architecture:  Component A (UPF reality) only")
    print(f"               Components B+C fed by Azure Vision in v3\n")

    input_path = find_latest_clean(SAMPLE_DIR)
    df = analyze(input_path)

    eligible = df[df["nlp_eligible"] == True].copy()
    eligible["health_wash_score_v1"] = pd.to_numeric(
        eligible["health_wash_score_v1"], errors="coerce"
    )

    print(f"\n  -- Summary --------------------------------------------------")
    print(f"  Total rows:   {len(df):,}")
    print(f"  NLP analyzed: {len(eligible):,}")

    print(f"\n  Top 10 products by UPF reality score (v1):")
    top = eligible.nlargest(10, "health_wash_score_v1")[
        ["product_name", "brands", "health_wash_score_v1", "upf_markers_found"]
    ]
    pd.set_option("display.max_colwidth", 35)
    print("  " + top.to_string().replace("\n", "\n  "))

    print(f"\n  Half-truth patterns:")
    for col, label in [
        ("ht_sugar_loophole",    "HT-1 sugar loophole"),
        ("ht_protein_masks_fat", "HT-2 protein masks fat"),
        ("ht_fibre_distraction", "HT-3 fibre distraction"),
        ("ht_vegan_calorie_trap","HT-4 vegan calorie trap"),
    ]:
        subset = eligible[eligible[col] == True]
        if len(subset):
            top3 = subset["primary_brand"].value_counts().head(3)
            print(f"    {label}: {len(subset):,} | top: {dict(top3)}")
        else:
            print(f"    {label}: 0 products")

    output_path = os.path.join(SAMPLE_DIR, f"analyzed_{timestamp}.csv")
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n  Saved -> analyzed_{timestamp}.csv")
    print(f"  ({len(df):,} rows, {len(df.columns)} columns)")
    print(f"\n  v3 bridge: joins on 'barcode'")
    print(f"  Pending: health_wash_score_v3 (merge_scores.py after Azure)\n")


if __name__ == "__main__":
    main()