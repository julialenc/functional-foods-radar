"""
app.py
------
Functional Food Radar — Streamlit prototype
Category ladder view: filter by category + country, rank by nutrition,
show claim flags and product images.

Usage:
    streamlit run app.py

Requirements:
    pip install streamlit pandas sqlite3

Data:
    database/functional_food_radar.db  (production DB)
    data/reference/company_brand_mapping.csv
"""

import sqlite3
import pandas as pd
import streamlit as st
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

ROOT    = Path(__file__).parent
DB_PATH = ROOT / "database" / "functional_food_radar.db"
MAPPING = ROOT / "data" / "reference" / "company_brand_mapping.csv"

st.set_page_config(
    page_title="Functional Food Radar",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ───────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

.radar-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    padding: 2rem 2.5rem;
    border-radius: 12px;
    margin-bottom: 1.5rem;
    color: white;
}

.radar-header h1 {
    font-size: 1.8rem;
    font-weight: 600;
    margin: 0 0 0.3rem 0;
    letter-spacing: -0.02em;
}

.radar-header p {
    font-size: 0.9rem;
    opacity: 0.7;
    margin: 0;
}

.metric-card {
    background: #f8f9ff;
    border: 1px solid #e8eaf6;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    text-align: center;
}

.metric-card .value {
    font-size: 1.8rem;
    font-weight: 600;
    color: #1a1a2e;
    font-family: 'DM Mono', monospace;
}

.metric-card .label {
    font-size: 0.75rem;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 0.2rem;
}

.claim-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 20px;
    font-size: 0.7rem;
    font-weight: 500;
    margin: 2px;
    font-family: 'DM Mono', monospace;
}

.badge-protein   { background: #e8f5e9; color: #2e7d32; }
.badge-sugar     { background: #fff3e0; color: #e65100; }
.badge-gut       { background: #f3e5f5; color: #6a1b9a; }
.badge-immune    { background: #e3f2fd; color: #1565c0; }
.badge-natural   { background: #e8f5e9; color: #1b5e20; }
.badge-fortif    { background: #fce4ec; color: #880e4f; }
.badge-energy    { background: #fff8e1; color: #f57f17; }
.badge-vegan     { background: #e0f2f1; color: #004d40; }
.badge-default   { background: #f5f5f5; color: #424242; }

.score-high   { color: #c62828; font-weight: 600; }
.score-medium { color: #e65100; font-weight: 500; }
.score-low    { color: #2e7d32; font-weight: 500; }
.score-clean  { color: #1565c0; font-weight: 400; }

.ht-flag {
    display: inline-block;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.65rem;
    background: #ffebee;
    color: #b71c1c;
    font-weight: 600;
    margin: 1px;
}

.product-row {
    border-bottom: 1px solid #f0f0f0;
    padding: 0.5rem 0;
}
</style>
""", unsafe_allow_html=True)

# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_data():
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql("""
        SELECT
            p.barcode, p.product_name, p.brands, p.primary_brand,
            p.query_category, p.primary_country,
            p.nova_group, p.nutriscore_grade,
            p.energy_kcal, p.fat_100g, p.saturated_fat_100g,
            p.carbs_100g, p.sugars_100g, p.protein_100g,
            p.fiber_100g, p.salt_100g,
            p.image_url,
            r.health_wash_score_v1,
            r.health_wash_score_v3,
            r.health_wash_category_v3,
            r.upf_markers_found,
            r.functional_claims_found,
            r.negative_claims_found,
            r.v3_claims_found,
            r.ht_sugar_loophole,
            r.ht_protein_masks_fat,
            r.ht_fibre_distraction,
            r.ht_vegan_calorie_trap
        FROM products p
        LEFT JOIN nlp_results r ON p.barcode = r.barcode
        WHERE p.image_url IS NOT NULL
          AND p.image_url NOT LIKE '%/invalid/%'
          AND p.image_url != ''
    """, conn, dtype={"barcode": str})
    conn.close()
    return df


@st.cache_data
def load_mapping():
    if MAPPING.exists():
        return pd.read_csv(MAPPING)
    return pd.DataFrame()


# ── Helpers ───────────────────────────────────────────────────────────────────

BENEFIT_GROUPS = {
    "protein":      ["protein_claim", "protein_amount_g"],
    "sugar":        ["no_added_sugar", "reduced_sugar"],
    "gut":          ["probiotic_claim", "fibre_claim", "prebiotic_claim"],
    "immune":       ["immune_claim"],
    "natural":      ["natural_claim", "no_artificial", "clean_label_claim",
                     "no_palm_oil", "organic_claim"],
    "fortif":       ["fortification_claim"],
    "energy":       ["energy_claim"],
    "plant_based":  ["vegan_claim", "dairy_free_claim", "plant_based_claim"],
}

BADGE_CLASSES = {
    "protein": "badge-protein",
    "sugar":   "badge-sugar",
    "gut":     "badge-gut",
    "immune":  "badge-immune",
    "natural": "badge-natural",
    "fortif":  "badge-fortif",
    "energy":  "badge-energy",
    "plant_based": "badge-vegan",
}

HT_LABELS = {
    "ht_sugar_loophole":    "HT-1 sugar",
    "ht_protein_masks_fat": "HT-2 protein",
    "ht_fibre_distraction": "HT-3 fibre",
    "ht_vegan_calorie_trap":"HT-4 vegan",
}


def get_benefit_badges(claims_str):
    if not isinstance(claims_str, str):
        return ""
    badges = []
    for group, keywords in BENEFIT_GROUPS.items():
        if any(k in claims_str for k in keywords):
            cls = BADGE_CLASSES.get(group, "badge-default")
            badges.append(f'<span class="claim-badge {cls}">{group}</span>')
    return " ".join(badges)


def get_ht_flags(row):
    flags = []
    for col, label in HT_LABELS.items():
        if row.get(col) in [True, 1]:
            flags.append(f'<span class="ht-flag">⚠ {label}</span>')
    return " ".join(flags)


def score_color_class(score):
    if pd.isna(score):
        return "score-clean"
    if score >= 70:
        return "score-high"
    if score >= 45:
        return "score-medium"
    if score >= 20:
        return "score-low"
    return "score-clean"


def nutriscore_emoji(grade):
    mapping = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴", "E": "🔴"}
    return mapping.get(str(grade).upper(), "⚪")


# ── App ───────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="radar-header">
    <h1>🔍 Functional Food Radar</h1>
    <p>Front-of-pack claim analysis across 845K products — understanding what brands say vs what products contain</p>
</div>
""", unsafe_allow_html=True)

# Load data
with st.spinner("Loading database..."):
    df = load_data()
    mapping = load_mapping()

# ── Sidebar filters ───────────────────────────────────────────────────────────

st.sidebar.header("Filters")

# Category
categories = sorted(df["query_category"].dropna().unique().tolist())
selected_category = st.sidebar.selectbox(
    "Category",
    ["All"] + categories,
    index=0
)

# Country
countries = sorted(df["primary_country"].dropna().unique().tolist())
selected_country = st.sidebar.selectbox(
    "Country",
    ["All"] + countries[:50],
    index=0
)

# Brand filter
brands = sorted(df["primary_brand"].dropna().unique().tolist())
selected_brand = st.sidebar.selectbox(
    "Brand (optional)",
    ["All"] + brands[:200],
    index=0
)

# Nutriscore filter
nutriscore_options = ["All", "A", "B", "C", "D", "E"]
selected_nutriscore = st.sidebar.multiselect(
    "Nutriscore grade",
    ["A", "B", "C", "D", "E"],
    default=[]
)

# NOVA filter
nova_options = st.sidebar.multiselect(
    "NOVA group",
    [1, 2, 3, 4],
    default=[]
)

# Claims filter
st.sidebar.subheader("Claim filter")
show_only_claimed = st.sidebar.checkbox("Only products with v3 claims", value=False)
show_only_ht = st.sidebar.checkbox("Only half-truth patterns", value=False)

# Rank by
rank_by = st.sidebar.selectbox(
    "Rank by",
    ["health_wash_score_v3", "health_wash_score_v1",
     "protein_100g", "sugars_100g", "energy_kcal",
     "fat_100g", "saturated_fat_100g"],
    index=0
)

rank_ascending = st.sidebar.checkbox("Ascending order", value=False)

# Results limit
n_results = st.sidebar.slider("Products to show", 10, 200, 50)

# ── Filter data ───────────────────────────────────────────────────────────────

filtered = df.copy()

if selected_category != "All":
    filtered = filtered[filtered["query_category"] == selected_category]

if selected_country != "All":
    filtered = filtered[filtered["primary_country"] == selected_country]

if selected_brand != "All":
    filtered = filtered[filtered["primary_brand"] == selected_brand]

if selected_nutriscore:
    filtered = filtered[
        filtered["nutriscore_grade"].str.upper().isin(selected_nutriscore)
    ]

if nova_options:
    filtered = filtered[filtered["nova_group"].isin(nova_options)]

if show_only_claimed:
    filtered = filtered[
        filtered["v3_claims_found"].notna() &
        (filtered["v3_claims_found"] != "")
    ]

if show_only_ht:
    ht_mask = (
        (filtered["ht_sugar_loophole"].isin([True, 1])) |
        (filtered["ht_protein_masks_fat"].isin([True, 1])) |
        (filtered["ht_fibre_distraction"].isin([True, 1])) |
        (filtered["ht_vegan_calorie_trap"].isin([True, 1]))
    )
    filtered = filtered[ht_mask]

# Sort
sort_col = rank_by
if sort_col in filtered.columns:
    filtered = filtered.sort_values(
        sort_col, ascending=rank_ascending, na_position="last"
    )

filtered = filtered.head(n_results)

# ── Summary metrics ───────────────────────────────────────────────────────────

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="value">{len(filtered):,}</div>
        <div class="label">Products shown</div>
    </div>""", unsafe_allow_html=True)

with col2:
    has_v3 = filtered["health_wash_score_v3"].notna().sum()
    st.markdown(f"""
    <div class="metric-card">
        <div class="value">{has_v3:,}</div>
        <div class="label">With v3 score</div>
    </div>""", unsafe_allow_html=True)

with col3:
    high_score = (filtered["health_wash_score_v3"] >= 70).sum()
    st.markdown(f"""
    <div class="metric-card">
        <div class="value">{high_score:,}</div>
        <div class="label">HIGH score (≥70)</div>
    </div>""", unsafe_allow_html=True)

with col4:
    ht_count = sum([
        filtered[c].isin([True,1]).sum()
        for c in ["ht_sugar_loophole","ht_protein_masks_fat",
                  "ht_fibre_distraction","ht_vegan_calorie_trap"]
    ])
    st.markdown(f"""
    <div class="metric-card">
        <div class="value">{ht_count:,}</div>
        <div class="label">Half-truth flags</div>
    </div>""", unsafe_allow_html=True)

with col5:
    avg_v1 = filtered["health_wash_score_v1"].mean()
    st.markdown(f"""
    <div class="metric-card">
        <div class="value">{avg_v1:.1f}</div>
        <div class="label">Avg v1 score</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["📊 Category ladder", "🏷 Brand summary", "📈 Score distribution"])

# ── Tab 1: Category ladder ────────────────────────────────────────────────────

with tab1:
    st.subheader(f"Product ranking — {selected_category} / {selected_country}")

    for _, row in filtered.iterrows():
        with st.container():
            c1, c2, c3, c4 = st.columns([1, 3, 2, 2])

            # Image
            with c1:
                if pd.notna(row.get("image_url")) and row["image_url"]:
                    st.image(row["image_url"], width=80)

            # Product info
            with c2:
                name = row.get("product_name") or "Unknown product"
                brand = row.get("primary_brand") or ""
                st.markdown(f"**{name[:60]}**")
                st.caption(f"{brand} · {row.get('query_category','')}")

                # Nutriscore + NOVA
                ns = nutriscore_emoji(row.get("nutriscore_grade",""))
                nova = row.get("nova_group")
                nova_str = f"NOVA {int(nova)}" if pd.notna(nova) else "NOVA ?"
                st.caption(f"{ns} Nutriscore {row.get('nutriscore_grade','?')} · {nova_str}")

                # Claims
                claims = row.get("v3_claims_found") or row.get("functional_claims_found") or ""
                badges = get_benefit_badges(claims)
                if badges:
                    st.markdown(badges, unsafe_allow_html=True)

                # Half-truth flags
                ht_flags = get_ht_flags(row)
                if ht_flags:
                    st.markdown(ht_flags, unsafe_allow_html=True)

            # Nutrition
            with c3:
                kcal = row.get("energy_kcal")
                protein = row.get("protein_100g")
                sugar = row.get("sugars_100g")
                fat = row.get("saturated_fat_100g")

                if pd.notna(kcal):
                    st.metric("kcal/100g", f"{kcal:.0f}")
                col_a, col_b = st.columns(2)
                with col_a:
                    if pd.notna(protein):
                        st.metric("Protein", f"{protein:.1f}g")
                with col_b:
                    if pd.notna(sugar):
                        st.metric("Sugar", f"{sugar:.1f}g")

            # Scores
            with c4:
                v1 = row.get("health_wash_score_v1")
                v3 = row.get("health_wash_score_v3")

                if pd.notna(v1):
                    st.metric("v1 UPF score", f"{v1:.0f}/40")
                if pd.notna(v3):
                    cls = score_color_class(v3)
                    st.markdown(
                        f'<span class="{cls}">v3 score: {v3:.0f}/100</span>',
                        unsafe_allow_html=True
                    )
                    cat = row.get("health_wash_category_v3") or ""
                    if cat:
                        st.caption(cat.split("—")[0].strip())

            st.divider()

# ── Tab 2: Brand summary ──────────────────────────────────────────────────────

with tab2:
    st.subheader("Brand summary")

    brand_df = df.copy()
    if selected_category != "All":
        brand_df = brand_df[brand_df["query_category"] == selected_category]
    if selected_country != "All":
        brand_df = brand_df[brand_df["primary_country"] == selected_country]

    brand_stats = brand_df.groupby("primary_brand").agg(
        n_products=("barcode", "count"),
        avg_v1=("health_wash_score_v1", "mean"),
        avg_v3=("health_wash_score_v3", "mean"),
        avg_protein=("protein_100g", "mean"),
        avg_sugar=("sugars_100g", "mean"),
        avg_kcal=("energy_kcal", "mean"),
        ht_count=("ht_sugar_loophole", "sum"),
    ).reset_index()

    brand_stats = brand_stats[brand_stats["n_products"] >= 5].sort_values(
        "avg_v3", ascending=False, na_position="last"
    ).head(30)

    brand_stats = brand_stats.round(1)
    brand_stats.columns = [
        "Brand", "Products", "Avg v1", "Avg v3",
        "Avg protein", "Avg sugar", "Avg kcal", "HT flags"
    ]

    st.dataframe(
        brand_stats,
        use_container_width=True,
        hide_index=True,
    )

    # Parent company join
    if not mapping.empty:
        st.subheader("Parent company view")
        merged = brand_stats.merge(
            mapping[["brand", "parent_company"]].rename(
                columns={"brand": "Brand"}
            ),
            on="Brand", how="left"
        )
        company_stats = merged.groupby("parent_company").agg(
            brands=("Brand", "count"),
            avg_v3=("Avg v3", "mean"),
            total_products=("Products", "sum"),
        ).reset_index().round(1).sort_values("avg_v3", ascending=False)
        st.dataframe(company_stats, use_container_width=True, hide_index=True)

# ── Tab 3: Score distribution ─────────────────────────────────────────────────

with tab3:
    st.subheader("Score distribution")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**v1 UPF reality score (0-40)**")
        v1_data = filtered["health_wash_score_v1"].dropna()
        if len(v1_data):
            st.bar_chart(v1_data.value_counts().sort_index())

    with col_b:
        st.markdown("**v3 full gap score (0-100)**")
        v3_data = filtered["health_wash_score_v3"].dropna()
        if len(v3_data):
            st.bar_chart(v3_data.value_counts().sort_index())

    st.subheader("Half-truth pattern breakdown")
    ht_summary = {
        "HT-1 Sugar loophole":     int(filtered["ht_sugar_loophole"].isin([True,1]).sum()),
        "HT-2 Protein masks fat":  int(filtered["ht_protein_masks_fat"].isin([True,1]).sum()),
        "HT-3 Fibre distraction":  int(filtered["ht_fibre_distraction"].isin([True,1]).sum()),
        "HT-4 Vegan calorie trap": int(filtered["ht_vegan_calorie_trap"].isin([True,1]).sum()),
    }
    ht_df = pd.DataFrame.from_dict(
        ht_summary, orient="index", columns=["count"]
    )
    st.bar_chart(ht_df)

# ── Footer ────────────────────────────────────────────────────────────────────

st.markdown("---")
st.caption(
    "Functional Food Radar · Data: Open Food Facts · "
    "Pipeline: github.com/julialenc/functional-foods-radar · "
    "v3 scores based on Azure Vision OCR + GPT-4.1-nano claim extraction"
)