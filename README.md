# 🔍 Functional Food Radar

### Tracking the health-washing of packaged foods using open data



[!\[License: ODbL](https://img.shields.io/badge/Data%2525252525252525252520License-ODbL-blue)](https://opendatacommons.org/licenses/odbl/)

[!\[Python 3.9+](https://img.shields.io/badge/Python-3.9+-green)](https://www.python.org/)

[!\[Data: Open Food Facts](https://img.shields.io/badge/Data-Open%25252525252525252520Food%25252525252525252520Facts-orange)](https://world.openfoodfacts.org/)



\---



## The problem



The FMCG industry is undergoing what analysts call the \*Great Protein Reset\* — billions in acquisitions, every major brand retrofitting functional claims onto existing portfolios. Doritos now has protein. Kellogg's Trésor is "fortified." Gerblé biscuits claim to reduce fatigue via magnesium. Coca-Cola Zero positions itself as an energy product.



But does the nutritional reality match the claim?



This project answers that question systematically, at scale, using open data.



**We don't measure market share — we measure market intent. And intent is where trends begin.**



\---



## What this project does



The Functional Food Radar is a data pipeline that:



1\. Ingests product data from \[Open Food Facts](https://world.openfoodfacts.org/) — the world's largest open food database, with 4.4 million products

2\. Cleans and enriches the data — language detection, nutritional outlier capping, completeness scoring

3\. Applies bilingual (EN/FR) rule-based NLP to flag ultra-processed markers and functional claim language in ingredient lists

4\. Scores each product on a \*\*health-wash scale (0–100)\*\* measuring the gap between what a product signals and what it actually contains

5\. Stores results in SQLite and exports clean CSVs for dashboard analysis



**In v3 (in progress): LLM vision analysis reads front-of-pack images to extract actual marketing claims, computing the full *claim-vs-reality gap* metric.**



\---



## Who this is for



This project is designed to serve multiple audiences simultaneously:



**Public health researchers and epidemiologists**

Systematic evidence of health-washing patterns across product categories and brands. The health-wash score is auditable — every flag traces to a specific ingredient keyword. Suitable for citation in policy papers.



**Nutritionists and dietitians**

A practical tool for understanding what "High Protein," "No Added Sugar," and "Source of Magnesium" claims actually mean in context of the product's NOVA group and full ingredient list. The Gerblé case study (see `docs/DATA\_OBSERVATIONS.md`) illustrates this precisely.



**Marketers and CPG brand managers**

Competitive intelligence on functional claim trends — which claims are growing, which brands are using them, and how they correlate with nutritional profiles. The `weekly\_brand\_summary` table tracks this over time.



**CPG startup founders**

An honest landscape assessment of where functional claims are credible vs where they are noise. The protein claim pattern — high claim frequency, highly variable actual protein content — is particularly relevant for anyone building in this space.



**Regulators and NGOs**

Quantitative evidence for policy discussions on front-of-pack labelling, comparative claim regulation, and the health halo effect of sustainability certifications.



**Journalists and investigators**

A living database of health-washing patterns with specific, named examples. The Pringles, Gerblé and Hipro case studies are documented with exact scores and the markers that triggered them.



\---



## The health-wash score



Each product receives a score from 0 to 100. The score has three components:



**Component A — UPF reality (0–40 points)**

Severity-weighted count of ultra-processed markers in the ingredient list. Carrageenan (E407, IARC Group 2B) scores 3. Lecithin scores 1. Glucose syrup, maltodextrin, artificial sweeteners score 2–3.



**Component B — Claim inflation (0–30 points)**

Number and type of functional claims detected. More claims on a product raise the health-washing potential ceiling.



**Component C — Contradiction (0–30 points)**

Claim present AND NOVA group 4 = contradiction penalty. Claim present AND Nutriscore D/E = additional penalty. Protein claim with less than 10g protein per 100g = specific penalty.



**Score interpretation:**

* 0–19: CLEAN — no significant signals
* 20–44: LOW — minor signals
* 45–69: MEDIUM — some health-washing signals
* 70–100: HIGH — strong health-washing signals



**Note:** This is a v1 proxy score based on ingredient text analysis. v3 LLM vision will add the front-of-pack claim layer, expected to increase scores for products like Gerblé (v1: 68, v3 estimated: 85–90) where most claims are on the packaging, not in the ingredient list.



\---



## Key findings (development dataset, n=1,348)



**- 65%** of NLP-eligible products contain at least one ultra-processed marker

**- 28%** of products make functional claim language in their ingredient list or product name

**- 47** products contain artificial sweeteners, of which \*\*21\*\* simultaneously make health or energy claims

**- Gerblé** is the most systematic health-washing brand in the French sample — 49 products, all NOVA 4, all making fortification or functional claims, average score 33.1 (diluted by relatively clean ingredient profiles; front-of-pack claims not yet captured)

**- Pringles** scores highest (81/100) — 7 ultra-processed markers, protein claim, NOVA 4, Nutriscore D

**- Nature Valley Protein** bars score 72/100 — a brand built around the protein claim narrative, NOVA 4, glucose syrup, maltodextrin



\---



## The agentic commerce angle



AI shopping agents — autonomous systems that make purchase decisions on behalf of users — cannot be influenced by packaging design, colour psychology, or emotional marketing. They query structured data and evaluate against criteria.



The brands that win in an agentic shopping world are the ones with complete, accurate, structured nutritional data. Not the best marketing copy.



We compute a **completeness score (0–100)** for every product based on how many key structured fields are populated. This score is a proxy for **agentic readiness** — how well-positioned a brand is for a world where machines do the shopping.



Average completeness in our development dataset: **93.9/100** — higher than expected, reflecting that our sample skews toward well-documented products. The full bulk export will reveal the true distribution.



\---



## Repository structure



```

functional-food-radar/

│

├── pipeline/

│   ├── ingest.py          # OFF API pull with pagination and retry logic

│   ├── clean.py           # Data cleaning, language detection, completeness scoring

│   ├── analyze.py         # Option A NLP: ingredient flagging, health-wash score

│   └── load.py            # SQLite storage + Power BI CSV export

│

├── notebooks/

│   ├── check\_languages.py # Language distribution analysis (exploratory)

│   └── reality\_checks.py  # 4 data sanity checks (exploratory)

│

├── database/

│   └── schema.sql         # SQLite schema (human-readable reference)

│

├── data/

│   ├── raw/               # Raw JSON from API (gitignored)

│   └── sample/            # Clean and analyzed CSVs (gitignored, except .gitkeep)

│

├── docs/

│   ├── ADR.md             # Architecture Decision Record (this project's design log)

│   └── DATA\_OBSERVATIONS.md  # Running log of data quality findings

│

├── powerbi/

│   └── README.md          # Instructions for connecting Power BI

│

├── .env.example           # Environment variable template

├── .gitignore

├── requirements.txt

└── README.md

```



\---



## How to run



\*\*Prerequisites:\*\*Python 3.9+, \~500MB disk space for development data



```bash

# 1. Clone and set up environment

git clone https://github.com/julialenc/functional-foods-radar.git

cd functional-foods-radar

python -m venv .venv

.venv Scripts activate        # Windows

# source .venv/bin/activate   # Mac/Linux

pip install -r requirements.txt


# 2. Run the full pipeline

python pipeline/ingest.py     # Pulls \~1,400 products from OFF API

python pipeline/clean.py      # Cleans, detects language, scores completeness

python pipeline/analyze.py    # NLP flagging and health-wash scoring

python pipeline/load.py       # Loads into SQLite, exports Power BI CSVs

```



**Note on API availability:** The OFF search API is hosted on donated infrastructure and experiences 503 errors during European peak hours (12:00–20:00 CET). For reliable pulls, run `ingest.py` before 08:00 or after 21:00 CET. The retry logic handles transient failures automatically.



**For production scale:** See `docs/ADR.md` ADR-001 for the bulk export strategy (one-time download of full 4.4M product database, weekly API diff for new products).



\---



## Data source and license



Data is sourced from [Open Food Facts](https://world.openfoodfacts.org/), licensed under the **Open Database License (ODbL)**. This means:



* You may use and analyze the data freely
* Attribution is required: "Data from Open Food Facts — openfoodfacts.org"
* Derivative databases must be released under the same ODbL license
* Analysis results (scores, reports, dashboards) are not derivative databases and may be used freely



This project's code is MIT licensed. The analysis outputs (scores, observations, findings) are freely reusable with attribution.



\---



## Versioning roadmap



| Version | Status | Description |

|---|---|---|

| **v1** | ✅ Complete | Rule-based NLP pipeline, EN/FR, 1,348 products, SQLite |

| **v1.5** | 📋 Planned | German NLP, company mapping table, UK/US market filtering |

| **v2** | ⏸ Deferred | K-Means clustering on macronutrients (no deadline) |

| **v3** | 🚀 In progress | LLM vision: front-of-pack claim extraction, claim-reality gap |

| **Production** | 📋 Planned | Full OFF bulk export (\~50K products), weekly scheduler, Power BI |



**Why v2 is deferred:** K-Means clustering can be done any time at no cost. v3 LLM vision produces the highest-value analytical output — the claim-vs-reality gap. See `docs/ADR.md` ADR-005 and ADR-006.



\---



## Documented limitations



This project is honest about what it cannot do:



**No sales data:** Product counts proxy for market intent, not market share. A product existing in OFF does not mean it sells well.

**French market bias:** 69% of current sample is FR-language. Anglo-Saxon markets (UK, US) have significantly higher health-washing density but lower OFF coverage. UK/US filtering is planned with the full bulk export.

\*\*v1 NLP is claim-side blind:\*\*The ingredient list tells us what a product *is*. The front of pack tells us what it *claims to be*. v3 bridges this gap.

\*\*Crowdsourced data quality:\*\*OFF data is contributor-entered and variable in completeness. Reality checks are documented in `docs/DATA\_OBSERVATIONS.md`.

\*\*Brand fragmentation:\*\*Conglomerate brands (Nestlé, Danone) appear under multiple brand strings. `primary\_brand` normalisation reduces this; full company mapping is planned for v1.5.



\---



## Contributing



This is an open research project. Contributions welcome:



\*\* - Extending the NLP dictionary\*\* — especially German, Spanish and Arabic variants

\*\* - Company mapping table\*\*— brand string → parent company CSV

\*\* - New category analysis\*\* — dairy desserts, plant-based foods, sports nutrition

\*\* - Power BI template\*\* — connecting to the SQLite output



Please open an issue before submitting a pull request.



\---



## Citation



If you use this project in research or reporting, please cite:



```

Lenc, J. (2026). Functional Food Radar: Tracking health-washing in packaged 

foods using open data. GitHub. https://github.com/julialenc/functional-foods-radar

Data source: Open Food Facts (openfoodfacts.org), ODbL license.

```



\---



*Built with Open Food Facts data · Powered by Python · No advertising, no sponsored content*

