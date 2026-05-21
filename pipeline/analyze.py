"""
analyze.py
----------
Option A — Rule-based NLP ingredient flagging and health-wash scoring.

What this script does:
    1.  Load latest clean_*.csv automatically
    2.  Filter to NLP-eligible rows (EN + FR + BOTH only)
    3.  Flag ultra-processed markers in ingredients_text (EN + FR dictionary)
    4.  Flag functional/health claims in ingredients_text and product_name
    5.  Cross-check additives_tags for E-number markers (where available)
    6.  Detect "negative claims" (no added sugar, no lactose, natural etc.)
    7.  Compute a health-wash score per product (0-100)
    8.  Classify each product into a health-wash category
    9.  Save enriched CSV to data/sample/

Health-wash score logic:
    Higher score = more suspicious gap between claims and reality.
    Built to JOIN cleanly with v3 LLM vision claim extraction on barcode.

Usage:
    python pipeline/analyze.py

Input:
    data/sample/clean_<timestamp>.csv   (latest file auto-detected)

Output:FUNCTIONAL_CLAIM_MARKERS
    data/sample/analyzed_<timestamp>.csv

Architecture note (v2 stub):
    cluster_label column is passed through unchanged from clean.py.
    K-Means clustering (Option B) will populate it in v2.
    See docs/ADR.md.

Architecture note (v3 bridge):
    health_wash_score and claim_flags columns are designed to JOIN
    with v3 LLM vision output on barcode field.
    The gap between front-of-pack claims (v3) and reality (this script)
    is the core health-washing metric. See docs/ADR.md.
"""

import pandas as pd
import os
import re
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(ROOT, "data", "sample")


# ── Ultra-processed ingredient markers ───────────────────────────────────────
# Bilingual EN/FR dictionary.
# Each entry is a tuple: (keyword, label, severity)
# severity: 1 = minor additive, 2 = significant additive, 3 = strong UPF marker
#
# Sources:
#   - NOVA group 4 classification criteria (Monteiro et al. 2019)
#   - IARC classification for individual additives
#   - OFF additives database
#   - Emmi case study (OBS-009 in DATA_OBSERVATIONS.md)

ULTRA_PROCESSED_MARKERS = [

    # ── Sweeteners (artificial) ───────────────────────────────────────────────
    # EN/FR names + E-numbers (caught via ingredients_text or additives_tags)
    ("aspartame",           "artificial_sweetener", 3),
    ("acesulfame",          "artificial_sweetener", 3),
    ("acésulfame",          "artificial_sweetener", 3),
    ("saccharin",           "artificial_sweetener", 3),
    ("saccharine",          "artificial_sweetener", 3),
    ("sucralose",           "artificial_sweetener", 3),
    ("cyclamate",           "artificial_sweetener", 3),
    ("cyclamat",            "artificial_sweetener", 3),  # FR
    ("stevia",              "sweetener_natural",    1),
    ("steviol",             "sweetener_natural",    1),
    ("maltitol",            "polyol_sweetener",     2),
    ("sorbitol",            "polyol_sweetener",     2),
    ("xylitol",             "polyol_sweetener",     2),
    ("erythritol",          "polyol_sweetener",     1),
    ("vanilline",           "artificial_flavour",   2),  # FR: artificial vanillin

    # ── Emulsifiers ───────────────────────────────────────────────────────────
    ("lecithin",            "emulsifier",           1),
    ("lecithine",           "emulsifier",           1),   # FR
    ("lécithine",           "emulsifier",           1),   # FR accented
    ("mono- and diglycerides", "emulsifier",        2),
    ("monoglycérides",      "emulsifier",           2),   # FR
    ("diglycérides",        "emulsifier",           2),   # FR
    ("carrageenan",         "emulsifier_concern",   3),   # IARC 2B
    ("carraghénane",        "emulsifier_concern",   3),   # FR
    ("carraghénanes",       "emulsifier_concern",   3),   # FR plural
    ("xanthan",             "thickener",            2),
    ("xanthane",            "thickener",            2),   # FR
    ("guar",                "thickener",            1),
    ("carboxymethyl",       "thickener",            2),
    ("cellulose",           "thickener",            1),
    ("pectin",              "thickener",            1),
    ("pectine",             "thickener",            1),   # FR

    # ── Preservatives ─────────────────────────────────────────────────────────
    ("sodium benzoate",     "preservative",         2),
    ("benzoate de sodium",  "preservative",         2),   # FR
    ("potassium sorbate",   "preservative",         2),
    ("sorbate de potassium","preservative",         2),   # FR
    ("sodium nitrite",      "preservative",         3),
    ("nitrite de sodium",   "preservative",         3),   # FR
    ("sodium nitrate",      "preservative",         3),
    ("nitrate de sodium",   "preservative",         3),   # FR
    ("bha",                 "preservative",         3),
    ("bht",                 "preservative",         3),
    ("tbhq",                "preservative",         3),

    # ── Flavourings (generic) ─────────────────────────────────────────────────
    # "natural flavour" is a UPF indicator — real food doesn't need added flavour
    ("artificial flavour",  "artificial_flavour",   3),
    ("artificial flavor",   "artificial_flavour",   3),
    ("natural flavour",     "added_flavour",        2),
    ("natural flavor",      "added_flavour",        2),
    ("arôme naturel",       "added_flavour",        2),   # FR
    ("arôme artificiel",    "artificial_flavour",   3),   # FR
    ("arôme",               "added_flavour",        1),   # FR generic
    ("arome",               "added_flavour",        1),   # FR without accent
    ("flavouring",          "added_flavour",        1),
    ("flavoring",           "added_flavour",        1),

    # ── Glucose syrups and refined sugars ─────────────────────────────────────
    ("glucose syrup",       "glucose_syrup",        3),
    ("sirop de glucose",    "glucose_syrup",        3),   # FR
    ("high fructose",       "glucose_syrup",        3),
    ("corn syrup",          "glucose_syrup",        3),
    ("dextrose",            "refined_sugar",        2),
    ("maltodextrin",        "maltodextrin",         3),
    ("maltodextrine",       "maltodextrin",         3),   # FR

    # ── Refined starches ──────────────────────────────────────────────────────
    ("modified starch",     "modified_starch",      2),
    ("amidon modifié",      "modified_starch",      2),   # FR
    ("amidon",              "starch",               1),   # FR generic starch
    ("starch",              "starch",               1),

    # ── Industrial fats ───────────────────────────────────────────────────────
    ("palm oil",            "palm_oil",             2),
    ("huile de palme",      "palm_oil",             2),   # FR
    ("partially hydrogenated", "trans_fat",         3),
    ("interesterified",     "industrial_fat",       2),
    ("fractionated",        "industrial_fat",       1),

    # ── Raising agents (processed bread/bakery indicator) ─────────────────────
    ("sodium carbonate",    "raising_agent",        1),
    ("carbonate de sodium", "raising_agent",        1),   # FR
    ("ammonium carbonate",  "raising_agent",        1),
    ("carbonate d'ammonium","raising_agent",        1),   # FR
    ("sodium bicarbonate",  "raising_agent",        1),
    ("bicarbonate de sodium","raising_agent",       1),   # FR

    # ── Colours ───────────────────────────────────────────────────────────────
    ("caramel colour",      "artificial_colour",    2),
    ("caramel color",       "artificial_colour",    2),
    ("colorant",            "colour",               1),   # FR
    ("tartrazine",          "artificial_colour",    3),
    ("sunset yellow",       "artificial_colour",    3),
    ("brilliant blue",      "artificial_colour",    3),
    ("allura red",          "artificial_colour",    3),

    # ── Acid regulators ───────────────────────────────────────────────────────
    ("phosphoric acid",     "acid_regulator",       2),
    ("acide phosphorique",  "acid_regulator",       2),   # FR
    ("citric acid",         "acid_regulator",       1),
    ("acide citrique",      "acid_regulator",       1),   # FR
]

# ── E-number markers ──────────────────────────────────────────────────────────
# Checked against additives_tags field (pipe-separated OFF pre-parsed list).
# These are the most significant E-numbers for health-washing detection.
# Format: (e_number_substring, label, severity)

E_NUMBER_MARKERS = [
    ("e950",  "artificial_sweetener", 3),   # Acesulfame-K
    ("e951",  "artificial_sweetener", 3),   # Aspartame
    ("e952",  "artificial_sweetener", 3),   # Cyclamate (banned in US/Canada)
    ("e954",  "artificial_sweetener", 3),   # Saccharin
    ("e955",  "artificial_sweetener", 3),   # Sucralose
    ("e960",  "sweetener_natural",    1),   # Steviol glycosides
    ("e407",  "emulsifier_concern",   3),   # Carrageenan (IARC 2B)
    ("e322",  "emulsifier",           1),   # Lecithin
    ("e471",  "emulsifier",           2),   # Mono/diglycerides
    ("e415",  "thickener",            2),   # Xanthan gum
    ("e412",  "thickener",            1),   # Guar gum
    ("e150d", "artificial_colour",    2),   # Caramel colour IV (sulfite process)
    ("e250",  "preservative",         3),   # Sodium nitrite
    ("e251",  "preservative",         3),   # Sodium nitrate
    ("e211",  "preservative",         2),   # Sodium benzoate
    ("e202",  "preservative",         2),   # Potassium sorbate
    ("e338",  "acid_regulator",       2),   # Phosphoric acid
    ("e330",  "acid_regulator",       1),   # Citric acid
    ("e621",  "flavour_enhancer",     2),   # MSG
    ("e160b", "colour",               1),   # Annatto (natural but allergenic)
]

# ── Functional / health claim markers ─────────────────────────────────────────
# These appear in ingredients_text, product_name, or labels field.
# Presence of these = product is making a functional claim.
# Used to compute the CLAIM side of the health-wash gap (v1 proxy).
# v3 LLM vision will replace/supplement this with front-of-pack extraction.
#
# Format: (keyword, claim_category)

FUNCTIONAL_CLAIM_MARKERS = [

    # ── Protein claims ────────────────────────────────────────────────────────
    ("whey protein",        "protein_claim"),
    ("whey protein isolate","protein_claim"),
    ("protéines de lactosérum", "protein_claim"),  # FR: whey protein specific
    ("casein",              "protein_claim"),
    ("protein",             "protein_claim"),
    ("protéine",            "protein_claim"),   # FR
    ("proteines",           "protein_claim"),   # FR plural without accent
    ("high protein",        "protein_claim"),
    ("high-protein",        "protein_claim"),
    ("riche en protéines",  "protein_claim"),   # FR: rich in protein

    # ── Probiotic / gut health ────────────────────────────────────────────────
    ("probiotic",           "probiotic_claim"),
    ("probiotique",         "probiotic_claim"),  # FR
    ("lactobacillus",       "probiotic_claim"),
    ("bifidobacterium",     "probiotic_claim"),
    ("bifidus",             "probiotic_claim"),
    ("bacteria",            "probiotic_claim"),  # generic bacteria mention
    ("live cultures",       "probiotic_claim"),
    ("ferments lactiques",  "probiotic_claim"),  # FR

    # ── Prebiotic / fibre ────────────────────────────────────────────────────
    ("prebiotic",           "prebiotic_claim"),
    ("prébiotique",         "prebiotic_claim"),  # FR
    ("inulin",              "prebiotic_claim"),
    ("inuline",             "prebiotic_claim"),  # FR
    ("chicory root",        "prebiotic_claim"),
    ("inulin de chicorée",  "prebiotic_claim"),  # FR — specific prebiotic form
    ("extrait de chicorée", "prebiotic_claim"),  # FR — extract form
    ("fructooligosaccharides", "prebiotic_claim"),
    ("fos",                 "prebiotic_claim"),
    ("source de fibres",    "fibre_claim"),      # FR regulated claim
    ("source of fibre",     "fibre_claim"),       # EN
    ("source of fiber",     "fibre_claim"),       # EN US
    ("riche en fibres",     "fibre_claim"),       # FR: high in fibre
    ("high in fibre",       "fibre_claim"),       # EN
    ("germe de blé",        "fortification_claim"), # FR: wheat germ — Gerblé signature
    ("wheat germ",          "fortification_claim"), # EN

    # ── Vitamins and minerals (fortification claims) ──────────────────────────
    ("vitamin",             "fortification_claim"),
    ("vitamine",            "fortification_claim"),  # FR
    ("calcium",             "fortification_claim"),
    ("magnesium",           "fortification_claim"),
    ("magnésium",           "fortification_claim"),  # FR
    ("iron",                "fortification_claim"),
    ("fer",                 "fortification_claim"),  # FR: iron
    ("zinc",                "fortification_claim"),
    ("omega",               "fortification_claim"),
    ("collagen",            "fortification_claim"),
    ("collagène",           "fortification_claim"),  # FR

    # ── Adaptogens / superfoods ────────────────────────────────────────────────
    ("ashwagandha",         "adaptogen_claim"),
    ("maca",                "adaptogen_claim"),
    ("turmeric extract",    "adaptogen_claim"),
    ("curcumin",            "adaptogen_claim"),
    ("extrait de curcuma",  "adaptogen_claim"),  # FR — extract specifically
    ("ginseng",             "adaptogen_claim"),
    ("matcha",              "adaptogen_claim"),
    ("spirulina",           "adaptogen_claim"),
    ("spiruline",           "adaptogen_claim"),  # FR
    ("chlorella",           "adaptogen_claim"),
    ("acai",                "adaptogen_claim"),
    ("açaí",                "adaptogen_claim"),
    ("goji",                "adaptogen_claim"),
    ("moringa",             "adaptogen_claim"),
    ("baobab",              "adaptogen_claim"),

    # ── Keto / low carb ───────────────────────────────────────────────────────
    ("keto",                "keto_claim"),
    ("ketogenic",           "keto_claim"),
    ("cétogène",            "keto_claim"),  # FR
    ("low carb",            "keto_claim"),
    ("low-carb",            "keto_claim"),

    # ── Energy / performance ──────────────────────────────────────────────────
    ("caffeine",            "energy_claim"),
    ("caféine",             "energy_claim"),  # FR
    ("guarana",             "energy_claim"),
    ("taurine",             "energy_claim"),
    ("creatine",            "energy_claim"),
    ("créatine",            "energy_claim"),  # FR
    ("bcaa",                "energy_claim"),
    ("electrolyte",         "energy_claim"),
    ("électrolyte",         "energy_claim"),  # FR
]

# ── Negative claim markers ────────────────────────────────────────────────────
# "No X" claims on packaging — technically true but often misleading.
# Detected in product_name and labels field.
# These are the FRONT-OF-PACK claim proxies for v1.
# v3 LLM vision will give the full picture.

NEGATIVE_CLAIM_MARKERS = [
    # EN
    ("no added sugar",      "no_added_sugar"),
    ("no sugar added",      "no_added_sugar"),
    ("sugar free",          "no_added_sugar"),
    ("sugar-free",          "no_added_sugar"),
    ("no lactose",          "no_lactose"),
    ("lactose free",        "no_lactose"),
    ("lactose-free",        "no_lactose"),
    ("no gluten",           "no_gluten"),
    ("gluten free",         "no_gluten"),
    ("gluten-free",         "no_gluten"),
    ("no preservatives",    "no_preservatives"),
    ("preservative free",   "no_preservatives"),
    ("no artificial",       "no_artificial"),
    ("all natural",         "natural_claim"),
    ("100% natural",        "natural_claim"),
    ("clean label",         "clean_label"),
    ("no palm oil",         "no_palm_oil"),
    ("palm oil free",       "no_palm_oil"),
    ("non gmo",             "non_gmo"),
    ("non-gmo",             "non_gmo"),
    # FR
    ("sans sucre ajouté",   "no_added_sugar"),
    ("sans sucres ajoutés", "no_added_sugar"),
    ("sans sucre",          "no_added_sugar"),
    ("sans lactose",        "no_lactose"),
    ("sans gluten",         "no_gluten"),
    ("sans conservateur",   "no_preservatives"),
    ("sans conservateurs",  "no_preservatives"),
    ("sans additif",        "no_additives"),
    ("sans additifs",       "no_additives"),
    ("sans colorant",       "no_artificial"),
    ("sans arôme artificiel", "no_artificial"),
    ("naturel",             "natural_claim"),
    ("100% naturel",        "natural_claim"),
    ("sans huile de palme", "no_palm_oil"),
    ("moins de sucre",      "reduced_sugar"),   # "less sugar" — softer claim
    ("réduit en sucres",    "reduced_sugar"),
    ("aucun colorant",      "no_artificial"),    # FR: no colourant
    ("sans colorants",      "no_artificial"),    # FR plural
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_latest_clean(sample_dir):
    """Auto-detect the most recently created clean_*.csv file."""
    files = [
        f for f in os.listdir(sample_dir)
        if f.startswith("clean_") and f.endswith(".csv")
    ]
    if not files:
        raise FileNotFoundError(
            f"No clean_*.csv found in {sample_dir}. Run clean.py first."
        )
    files.sort(reverse=True)
    return os.path.join(sample_dir, files[0])


def flag_text(text, markers):
    """
    Scan text (lowercased) against a list of (keyword, label, ...) markers.
    Returns list of (keyword_found, label) tuples.
    Uses word-boundary aware matching to avoid false positives
    (e.g. 'iron' should not match 'environment').
    """
    if not isinstance(text, str) or text.strip() == "":
        return []

    text_lower = text.lower()
    found = []
    seen_labels = set()

    for marker in markers:
        keyword = marker[0]
        label   = marker[1]

        # Skip if we already found this label (avoid double-counting)
        if label in seen_labels:
            continue

        # Use word-boundary matching for short keywords (< 5 chars)
        # to avoid false positives like 'fer' matching 'differently'
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
    """
    Scan pipe-separated additives_tags string against E-number markers.
    Returns list of (e_number, label, severity) tuples.
    """
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


def compute_health_wash_score(upf_flags, claim_flags, neg_claim_flags,
                               nova_group, nutriscore, protein_100g):
    """
    Compute a health-wash score 0-100 for a single product.

    Logic:
        The score measures the GAP between what a product signals
        (functional claims, negative claims) and what it actually is
        (UPF markers, NOVA group, Nutriscore).

        High score = strong health claims + strong UPF reality = health-washing
        Low score  = no claims OR claims backed by good nutritional profile

    Components:
        A. UPF reality penalty (0-40 pts)
           Severity-weighted count of ultra-processed markers found.

        B. Claim inflation bonus (0-30 pts)
           Number and type of functional/negative claims made.
           More claims = higher potential for washing.

        C. NOVA/Nutriscore contradiction (0-30 pts)
           Claim present AND NOVA 3/4 = contradiction = high score.
           Claim present AND Nutriscore D/E = contradiction = high score.

    Note: this is a v1 PROXY score.
    v3 LLM vision will replace component B with actual front-of-pack
    claim extraction. The JOIN is on barcode field.
    See docs/ADR.md.
    """
    score = 0

    # ── Component A: UPF reality (0-40 pts) ─────────────────────────────────
    if upf_flags:
        severity_total = sum(f[2] for f in upf_flags)
        # Cap at 40 — more than enough signals above that
        score += min(severity_total * 3, 40)

    # ── Component B: Claim inflation (0-30 pts) ──────────────────────────────
    # Exclude pure energy_claim from inflation score
    # Energy drinks claiming energy is tautological, not health-washing
    non_energy_claims = [f for f in claim_flags
                         if f[1] != "energy_claim"]
    total_claims = len(non_energy_claims) + len(neg_claim_flags)
    score += min(total_claims * 5, 30)

    # ── Component C: NOVA / Nutriscore contradiction (0-30 pts) ─────────────
    has_claims = total_claims > 0

    if has_claims:
        # NOVA contradiction
        try:
            nova = float(nova_group) if nova_group else None
        except (ValueError, TypeError):
            nova = None

        # Only apply NOVA contradiction if there are non-energy claims
        has_non_energy_claims = any(
            f[1] != "energy_claim" for f in claim_flags
        )
        if nova in (3.0, 4.0) and has_non_energy_claims:
            score += 15 if nova == 3.0 else 20

        # Nutriscore contradiction
        ns = str(nutriscore).upper().strip() if nutriscore else ""
        if ns in ("D", "E"):
            score += 10

        # Special case: protein claim with low actual protein
        has_protein_claim = any(
            f[1] == "protein_claim" for f in claim_flags
        )
        try:
            prot = float(protein_100g) if protein_100g else None
        except (ValueError, TypeError):
            prot = None

        if has_protein_claim and prot is not None and prot < 10:
            score += 10  # protein claim with < 10g/100g is suspicious

    return min(score, 100)


def classify_health_wash(score):
    """
    Map numeric score to a human-readable category.
    Categories designed to be Power BI filter-friendly.
    """
    if score >= 70:
        return "HIGH — strong health-washing signals"
    elif score >= 45:
        return "MEDIUM — some health-washing signals"
    elif score >= 20:
        return "LOW — minor signals"
    else:
        return "CLEAN — no significant signals"


# ── Main analysis pipeline ────────────────────────────────────────────────────

def analyze(input_path):
    print(f"\n  Input file: {os.path.basename(input_path)}")
    df = pd.read_csv(input_path, encoding="utf-8-sig")
    print(f"  Rows on load: {len(df)}")

    # ── Step 1: Filter to NLP-eligible rows ──────────────────────────────────
    eligible = df[df["nlp_eligible"] == True].copy()
    ineligible = df[df["nlp_eligible"] != True].copy()
    print(f"\n  Step 1  - NLP eligible: {len(eligible)} rows")
    print(f"            NLP excluded: {len(ineligible)} rows "
          f"(OTHER/UNKNOWN — retained in output with null scores)")

    # ── Step 2: Flag ultra-processed markers ─────────────────────────────────
    print(f"\n  Step 2  - Flagging ultra-processed markers...")

    eligible["_upf_flags"] = eligible["ingredients_text"].apply(
        lambda x: flag_text(x, ULTRA_PROCESSED_MARKERS)
    )
    eligible["upf_marker_count"] = eligible["_upf_flags"].apply(len)
    eligible["upf_markers_found"] = eligible["_upf_flags"].apply(
        lambda flags: "|".join(f[1] for f in flags) if flags else ""
    )
    eligible["upf_max_severity"] = eligible["_upf_flags"].apply(
        lambda flags: max((f[2] for f in flags), default=0)
    )
    eligible["has_ultra_processed"] = eligible["upf_marker_count"] > 0

    upf_count = eligible["has_ultra_processed"].sum()
    print(f"            {upf_count} of {len(eligible)} products "
          f"({upf_count/len(eligible)*100:.0f}%) have UPF markers")

    # ── Step 3: Cross-check E-numbers from additives_tags ────────────────────
    print(f"\n  Step 3  - Cross-checking E-numbers from additives_tags...")

    eligible["_e_flags"] = eligible["additives_tags"].apply(
        lambda x: flag_additives(x, E_NUMBER_MARKERS)
    )
    eligible["e_number_count"] = eligible["_e_flags"].apply(len)
    eligible["e_numbers_found"] = eligible["_e_flags"].apply(
        lambda flags: "|".join(f[0] for f in flags) if flags else ""
    )
    # Flag artificial sweeteners specifically (high-value signal)
    eligible["has_artificial_sweetener"] = eligible["_e_flags"].apply(
        lambda flags: any(f[1] == "artificial_sweetener" for f in flags)
    )
    # Also check ingredients_text for sweetener names (catches nulls in additives_tags)
    sweetener_keywords = [m for m in ULTRA_PROCESSED_MARKERS
                          if m[1] == "artificial_sweetener"]
    eligible["has_artificial_sweetener"] = eligible.apply(
        lambda row: row["has_artificial_sweetener"] or bool(
            flag_text(row["ingredients_text"], sweetener_keywords)
        ), axis=1
    )

    e_count = (eligible["e_number_count"] > 0).sum()
    sweet_count = eligible["has_artificial_sweetener"].sum()
    print(f"            {e_count} products have flagged E-numbers")
    print(f"            {sweet_count} products contain artificial sweeteners")

    # ── Step 4: Flag functional claims ───────────────────────────────────────
    print(f"\n  Step 4  - Flagging functional claims...")

    # Search in both ingredients_text AND product_name
    eligible["_claim_flags"] = eligible.apply(
        lambda row: flag_text(
            str(row["ingredients_text"]) + " " + str(row["product_name"]),
            FUNCTIONAL_CLAIM_MARKERS
        ), axis=1
    )
    eligible["functional_claim_count"] = eligible["_claim_flags"].apply(len)
    eligible["functional_claims_found"] = eligible["_claim_flags"].apply(
        lambda flags: "|".join(f[1] for f in flags) if flags else ""
    )

    claim_count = (eligible["functional_claim_count"] > 0).sum()
    print(f"            {claim_count} products have functional claim markers")

    # Top claims breakdown
    all_claims = []
    for flags in eligible["_claim_flags"]:
        all_claims.extend(f[1] for f in flags)
    if all_claims:
        from collections import Counter
        top_claims = Counter(all_claims).most_common(8)
        print(f"            Top claim categories:")
        for claim, count in top_claims:
            print(f"              {claim:<30} {count} products")

    # ── Step 5: Flag negative claims ─────────────────────────────────────────
    print(f"\n  Step 5  - Flagging negative claims (no sugar, natural, etc.)...")

    # Search in product_name + labels field
    eligible["_neg_claim_flags"] = eligible.apply(
        lambda row: flag_text(
            str(row["product_name"]) + " " + str(row["labels"]),
            NEGATIVE_CLAIM_MARKERS
        ), axis=1
    )
    eligible["negative_claim_count"] = eligible["_neg_claim_flags"].apply(len)
    eligible["negative_claims_found"] = eligible["_neg_claim_flags"].apply(
        lambda flags: "|".join(f[1] for f in flags) if flags else ""
    )

    neg_count = (eligible["negative_claim_count"] > 0).sum()
    print(f"            {neg_count} products have negative claim markers")

    # ── Step 6: Compute health-wash score ────────────────────────────────────
    print(f"\n  Step 6  - Computing health-wash scores...")

    eligible["health_wash_score"] = eligible.apply(
        lambda row: compute_health_wash_score(
            upf_flags    = row["_upf_flags"],
            claim_flags  = row["_claim_flags"],
            neg_claim_flags = row["_neg_claim_flags"],
            nova_group   = row.get("nova_group"),
            nutriscore   = row.get("nutriscore_grade"),
            protein_100g = row.get("protein_100g"),
        ), axis=1
    )
    eligible["health_wash_category"] = eligible["health_wash_score"].apply(
        classify_health_wash
    )

    score_dist = eligible["health_wash_category"].value_counts()
    print(f"            Score distribution:")
    for cat, count in score_dist.items():
        print(f"              {cat:<40} {count}")

    # ── Step 7: Drop internal flag columns, keep clean output ────────────────
    drop_cols = ["_upf_flags", "_claim_flags", "_neg_claim_flags", "_e_flags"]
    eligible = eligible.drop(columns=[c for c in drop_cols if c in eligible.columns])

    # ── Step 8: Reattach ineligible rows (nulls for NLP columns) ─────────────
    nlp_output_cols = [
        "upf_marker_count", "upf_markers_found", "upf_max_severity",
        "has_ultra_processed", "e_number_count", "e_numbers_found",
        "has_artificial_sweetener", "functional_claim_count",
        "functional_claims_found", "negative_claim_count",
        "negative_claims_found", "health_wash_score", "health_wash_category"
    ]
    for col in nlp_output_cols:
        if col not in ineligible.columns:
            ineligible[col] = None

    df_out = pd.concat([eligible, ineligible], ignore_index=True)
    df_out = df_out.sort_values("barcode").reset_index(drop=True)

    return df_out


# ── Run ───────────────────────────────────────────────────────────────────────

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\nFunctional Food Radar — analyze.py")
    print(f"Run timestamp: {timestamp}")

    input_path = find_latest_clean(SAMPLE_DIR)
    df = analyze(input_path)

    # ── Summary ───────────────────────────────────────────────────────────────
    eligible = df[df["nlp_eligible"] == True].copy()
    eligible["health_wash_score"] = pd.to_numeric(
        eligible["health_wash_score"], errors="coerce"
    )

    print(f"\n  -- Summary --------------------------------------------------")
    print(f"  Total rows:     {len(df)}")
    print(f"  NLP analyzed:   {len(eligible)}")

    print(f"\n  Top 10 most health-washed products:")
    top = eligible.nlargest(10, "health_wash_score")[
        ["product_name", "brands", "health_wash_score",
         "health_wash_category", "nova_group", "nutriscore_grade",
         "upf_markers_found", "functional_claims_found"]
    ]
    pd.set_option("display.max_colwidth", 30)
    print("  " + top.to_string().replace("\n", "\n  "))

    print(f"\n  Products with artificial sweeteners + health claims:")
    paradox = eligible[
        eligible["has_artificial_sweetener"] &
        (eligible["functional_claim_count"] > 0)
    ][["product_name", "brands", "has_artificial_sweetener",
       "functional_claims_found", "health_wash_score"]]
    if len(paradox):
        print("  " + paradox.to_string().replace("\n", "\n  "))
    else:
        print("  None found in this sample")

    print(f"\n  NOVA 4 products with functional claims (core health-wash pattern):")
    core = eligible[
        (eligible["nova_group"] == 4.0) &
        (eligible["functional_claim_count"] > 0)
    ][["product_name", "brands", "nova_group",
       "nutriscore_grade", "functional_claims_found",
       "health_wash_score"]]
    if len(core):
        print("  " + core.to_string().replace("\n", "\n  "))
    else:
        print("  None found in this sample")

    # ── Save ──────────────────────────────────────────────────────────────────
    output_filename = f"analyzed_{timestamp}.csv"
    output_path     = os.path.join(SAMPLE_DIR, output_filename)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n  Saved -> {output_filename}")
    print(f"  ({len(df)} rows, {len(df.columns)} columns)\n")

    print(f"  v3 bridge: output joins to LLM vision results on 'barcode' field")
    print(f"  health_wash_score and functional_claims_found are the JOIN keys\n")


if __name__ == "__main__":
    main()
