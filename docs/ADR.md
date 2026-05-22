\# Architecture Decision Record (ADR)

\## Functional Food Radar



\*\*Version:\*\* 1.0  

\*\*Date:\*\* 20 May 2026  

\*\*Status:\*\* Active  

\*\*Authors:\*\* Julia Lenc  



\---



\## What is this document?



An Architecture Decision Record documents \*why\* the system was built the way it was — not just what it does. It is written for three audiences: a developer picking up the project in 6 months, a data analyst extending the analysis, and a non-technical stakeholder evaluating the project's credibility.



Every significant design decision is recorded here with its rationale, alternatives considered, and consequences. This makes the architecture auditable and the scope choices defensible.



\---



\## Project overview



The Functional Food Radar is a data pipeline and analysis system that tracks health-washing in packaged food products. It ingests product data from Open Food Facts (OFF), cleans and enriches it, applies NLP-based ingredient analysis, scores products on a health-washing scale, and stores results for dashboard consumption.



\*\*Core analytical question:\*\* Do functional food claims (High Protein, No Added Sugar, Natural, Probiotic) correlate with actual nutritional quality — or is there a systematic gap between what brands claim and what products contain?



\---



\## Decision log



\---



\### ADR-001 — Data source: Open Food Facts API + bulk export

\*\*Date:\*\* 18 May 2026  

\*\*Status:\*\* Active



\*\*Decision:\*\* Use Open Food Facts (OFF) as the primary data source, combining the Live JSON API for development and weekly incremental updates, and the OFF bulk CSV export for production-scale analysis.



\*\*Rationale:\*\*

OFF is the only open, crowdsourced, global food product database with structured nutritional data, ingredient lists, NOVA group classifications, and Nutriscore grades. Commercial alternatives (Nielsen, Mintel, Innova Market Insights) cost tens of thousands per year and do not permit redistribution. OFF data is licensed under ODbL — open for analysis, attribution required, share-alike for derivative databases.



\*\*Alternatives considered:\*\*

\- Scraping retailer websites (Carrefour, Tesco, Amazon Fresh): legally risky, technically fragile, no nutritional data

\- USDA FoodData Central: US-only, limited to \~600,000 products, no NOVA group

\- Commercial databases: cost-prohibitive for a research project, non-reproducible



\*\*Consequences:\*\*

\- Coverage bias toward Western Europe, especially France (see OBS-001)

\- Data quality is crowdsourced — variable completeness (see OBS-002)

\- No sales volume data — trend analysis is based on product launch counts, not market share (documented limitation)

\- Reproducible by anyone with internet access



\*\*Production strategy (OBS-012):\*\*

\- Week 0: download full OFF bulk export (\~9GB compressed, \~4.4M products), filter to relevant categories, load into SQLite

\- Weekly: query API for products with `last\_modified\_t` > 7 days, INSERT OR REPLACE on barcode

\- No full table scan required — `last\_modified\_t` index makes weekly diff fast



\---



\### ADR-002 — API fields: selective pull, not full record

\*\*Date:\*\* 18 May 2026  

\*\*Status:\*\* Active



\*\*Decision:\*\* Pull 15 active fields from the OFF API rather than full product records. A 16th field (`image_url`) is stubbed as a comment for v3 activation.



\*\*Fields pulled:\*\* code, product\_name, brands, categories, ingredients\_text, nutriments, nutriscore\_grade, nova\_group, countries\_tags, labels\_tags, quantity, packaging, created\_t, last\_modified\_t, additives\_tags, \[image\_url — commented out, v3]



\*\*Rationale:\*\* OFF records have 180+ fields. Full records are large and slow. We pull only what the analysis requires. `additives\_tags` is included because OFF pre-parses E-numbers from ingredient lists — this saves regex work in `analyze.py`. `image\_url` is commented out for v1 — included as a stub for v3 vision analysis.



\*\*Fields deliberately excluded from v1 (available for future versions):\*\*

\- `allergens\_tags` — useful for dietary analysis extensions

\- `ecoscore\_grade` — environmental impact, relevant for sustainability angle

\- `serving\_size` — needed for serving-based claim analysis

\- `stores` — retailer names, useful for market coverage analysis

\- `image\_url` — front-of-pack image, required for v3 LLM vision



\---



\### ADR-003 — Language scope: EN and FR only for NLP in v1

\*\*Date:\*\* 18 May 2026  

\*\*Status:\*\* Active



\*\*Decision:\*\* NLP ingredient flagging applies only to products with EN, FR, or BOTH ingredient text. OTHER and UNKNOWN language products are retained in the dataset with null NLP scores.



\*\*Rationale:\*\* Language distribution in sample (n=1,348): FR=69%, EN=11%, BOTH=3%, OTHER=14%, UNKNOWN=3%. Our NLP dictionary covers EN and FR — applying it to Arabic, Bulgarian, or German ingredient text produces silent false negatives (no flags where there should be flags). This is worse than openly flagging as ineligible. The `nlp\_eligible` boolean column makes this transparent in every downstream table.



\*\*German as v1.5 candidate (OBS-009):\*\* Austria is the third most represented country (10 products in development sample). German ingredient vocabulary shares significant overlap with EN/FR (maltodextrin, lecithin, glucose-sirup, palmöl). Extension to German is low-effort and planned for v1.5 after EN/FR NLP is validated at scale.



\*\*Consequences:\*\* 16% of products are not NLP-analyzed in v1. These products retain valid nutritional data and are included in nutritional analysis and future clustering (v2).



\---



\### ADR-004 — NLP approach: rule-based (Option A) in v1

\*\*Date:\*\* 18 May 2026  

\*\*Status:\*\* Active



\*\*Decision:\*\* Use rule-based regex/keyword NLP for ingredient flagging in v1. No ML models, no external NLP libraries beyond standard Python.



\*\*Options evaluated:\*\*

\- \*\*Option A (chosen): Rule-based/regex\*\* — bilingual EN/FR keyword dictionary, zero dependencies, transparent, auditable, fast, works offline

\- \*\*Option B: K-Means clustering\*\* — groups products by macronutrient profile, useful for "Actually Healthy vs Fake Healthy" segmentation, no claim detection capability

\- \*\*Option C: LLM extraction\*\* — extracts claims from packaging text/images, highest analytical value, requires API credits and infrastructure



\*\*Why Option A for v1:\*\*

Rule-based NLP is the only approach that produces \*auditable\* results. Every flag can be traced to a specific keyword in a specific ingredient field. This is essential for a project making claims about brand behaviour — you need to be able to show your work. A black-box ML model flagging a product as health-washed is not defensible to a brand's legal team or a regulator.



Option A also produces the `health\_wash\_score` that will serve as the REALITY side of the v3 claim-vs-reality gap metric. The gap between what `analyze.py` finds in the ingredient list and what the LLM vision finds on the front of pack is the core health-washing measurement.



\*\*Validation methodology:\*\* Always validate NLP dictionary on a small known sample before scaling. Three false positives were identified and fixed during development (OBS-010, OBS-013): curcuma as colorant, chicory fibre as texture, whey as confectionery ingredient. Manual review of top 20 scored products is mandatory before any new category or language is added.



\---



\### ADR-005 — v2 (K-Means clustering) deferred

\*\*Date:\*\* 19 May 2026  

\*\*Status:\*\* Deferred — no deadline



\*\*Decision:\*\* K-Means clustering on macronutrient data (Option B) is not implemented in v1. Infrastructure is ready for it but it is not prioritised.



\*\*Rationale:\*\* v3 LLM vision analysis has a hard deadline (Azure credits expire 31 May 2026) and higher analytical value. K-Means clustering costs nothing computationally and can be done at any time. The `cluster\_label` column is present as NULL in both `clean.py` output and SQLite schema — when v2 is implemented, it requires changing only `analyze.py` with no schema migration.



\*\*What v2 adds:\*\* Automatic product grouping into "Actually Healthy", "High Sugar/Fake Healthy", "Junk Food" clusters based on macronutrient profiles. Useful for Power BI scatter plot (sugar vs protein, coloured by cluster). Provides ground truth validation against OFF's own Nutriscore grades.



\*\*Stub in place:\*\* `analyze.py` contains a `cluster\_products()` stub function. `clean.py` adds `cluster\_label = None`. SQLite schema includes `cluster\_label TEXT` in `nlp\_results` table.



\---



\### ADR-006 — v3 (LLM vision) prioritised before v2

\*\*Date:\*\* 19 May 2026  

\*\*Status:\*\* Active



\*\*Decision:\*\* Skip v2 clustering and proceed directly to v3 LLM vision analysis before 31 May 2026.



\*\*Rationale:\*\* 100 CHF Azure credits expire 31 May 2026. LLM vision analysis has higher analytical value — it captures the CLAIM side of the health-washing equation, which rule-based NLP cannot. The claim-vs-reality gap is the core intellectual contribution of this project. Clustering is a nice-to-have grouping tool; claim extraction is the story.



\*\*Smart sampling strategy for v3:\*\* Do not analyze all products. Prioritize NOVA 4 products with functional label claims — these are the paradox products where health-washing is most likely. Expected \~15-20% of 9,000-product dataset = \~1,500-2,000 products. At $0.01-0.02 per image = $15-40 Azure spend, leaving significant buffer.



\*\*Cost controls:\*\* Set Azure cost alert at 80 CHF before any API calls. Test on 50 products before scaling. Use open source vision model (LLaVA, InternVL2) as alternative if credits are insufficient — public data warrants open tools.



\*\*v3 output joins to v1 on barcode:\*\* `health\_wash\_score` (reality, from `analyze.py`) + LLM-extracted claim list (from v3) → `claim\_reality\_gap` metric.



\---



\### ADR-007 — Storage: SQLite + CSV dual output

\*\*Date:\*\* 20 May 2026  

\*\*Status:\*\* Active



\*\*Decision:\*\* Store all pipeline output in SQLite with concurrent CSV export for Power BI.



\*\*Schema (4 tables):\*\*

\- `products` — identity + nutrition, UPSERT on barcode

\- `nlp\_results` — NLP scores and flags, UPSERT on barcode

\- `weekly\_brand\_summary` — pre-aggregated for Power BI trend charts

\- `ingestion\_log` — one row per pipeline run, full audit trail



\*\*Why SQLite not PostgreSQL:\*\* Single-user research project. SQLite is zero-infrastructure, file-based, version-controllable (schema.sql), and sufficient for hundreds of thousands of rows. Migration to PostgreSQL requires changing one connection string.



\*\*Why pre-aggregate for Power BI:\*\* DAX calculations on 100,000+ raw rows are slow and sometimes cause Power BI to hang. `weekly\_brand\_summary` pre-computes brand-level metrics in Python so Power BI does only rendering. This pattern scales to any dataset size.



\*\*UPSERT logic:\*\* `INSERT OR REPLACE` on barcode primary key. Safe to run multiple times. Handles OFF contributor corrections to existing products automatically.



\*\*WAL mode:\*\* `PRAGMA journal\_mode=WAL` enables safe concurrent reads while Python writes — important when Power BI is connected.



\---



\### ADR-008 — Brand normalisation: primary\_brand extraction

\*\*Date:\*\* 20 May 2026  

\*\*Status:\*\* Partial — v1.5 planned



\*\*Decision:\*\* Extract `primary\_brand` (first comma-separated token from `brands` field, accent-stripped) as a normalisation step in v1. Full company-to-brand mapping table planned for v1.5.



\*\*Problem:\*\* OFF `brands` field is free-text, contributor-entered. Same company appears as multiple strings: `nestlé`, `nestle`, `nestlé, nesquik`, `nestlé, chocapic`, `fitness` (Nestlé sub-brand), `perrier` (Nestlé water brand). This makes brand-level aggregation misleading (see OBS-014).



\*\*v1 fix:\*\* `primary\_brand` = first token, lowercased, accent-stripped (NFKD normalisation). Reduces fragmentation significantly. Gerblé → gerble (49 products). Nestlé consolidates partially but sub-brands (fitness, perrier) remain separate.



\*\*v1.5 fix:\*\* Company mapping table `company\_brands(brand\_string, parent\_company, sub\_brand)`. Manual curation of \~200-300 brand strings from 9,000-product dataset. Loaded as CSV, queried via JOIN in Power BI and summary queries.



\---



\### ADR-009 — Category scope: snacks, beverages, cereals in v1

\*\*Date:\*\* 18 May 2026  

\*\*Status:\*\* Active — to be expanded with bulk export



\*\*Decision:\*\* Query three OFF categories in v1: snacks, beverages, cereals.



\*\*Rationale:\*\* These three categories have the highest density of functional food claims and health-washing patterns. They cover the core use cases: protein bars, energy drinks, fortified breakfast cereals. They are also the categories most relevant to the audiences described in the README.



\*\*Known limitation (OBS-009, point B):\*\* OFF categories are contributor-assigned folksonomy tags, not a controlled vocabulary. Misclassification occurs (CRISTALINE water appearing in snacks). Category definitions will be refined using the full bulk export, where the OFF category hierarchy can be used for precise filtering.



\*\*Planned expansion:\*\* With the full bulk export, add `dairy-desserts` (Danone, Hipro, Actimel patterns) and `plant-based-foods` (Alpro, growing functional category). UK and US market filtering will be applied via `countries\_tags` field.



\*\*UK/US priority rationale:\*\* French market dominates current sample (69% FR language). UK and US markets have significantly higher health-washing density — protein bars, "clean label" snacks, superfood positioning are more aggressive in Anglo-Saxon markets. OFF coverage of UK/US products is lower than France but sufficient for trend analysis.


---

### ADR-010 — Architectural pivot: Component B and C fed by vision, not NLP
**Date:** 22 May 2026
**Status:** Active — implements from v3 onward

**Decision:** The health_wash_score Component B (claim inflation) and
Component C (contradiction) will be fed exclusively by Azure Vision
front-of-pack extraction output, not by ingredient text NLP.

**Rationale:**
Component B in v1 used ingredient text as a proxy for front-of-pack
claims. This produced systematic false positives at scale:
- Enriched flour vitamins (niacin, riboflavin) triggering fortification_claim
- Milk proteins as texture ingredients triggering protein_claim
- Natural colorants (curcumin, paprika) triggering adaptogen_claim
- Energy drinks making tautological energy claims scoring high

Root cause: ingredient text describes what a product CONTAINS.
Front-of-pack describes what a brand CLAIMS. These are different
information sources requiring different detection methods.

**New architecture (implemented in v3):**
  Component A (UPF reality, 0-40pts):
    Source: ingredients_text + additives_tags (NLP dictionary)
    Unchanged from v1

  Component B (claim inflation, 0-30pts):
    Source: Azure Vision OCR → GPT-4o-mini structured extraction
    Populated by vision_extract.py output, joined on barcode
    v1 interim: set to 0 until vision data available

  Component C (contradiction gap, 0-30pts):
    Source: vision claims × NOVA group × Nutriscore
    Populated after v3 merge in merge_scores.py
    v1 interim: NOVA/Nutriscore penalty only, no claim requirement

**Cost optimization (from practitioner input):**
  Tier 1: Azure AI Vision Read API (~1.50 CHF/1000 images) for OCR
  Tier 2: GPT-4o-mini on extracted text (not images) for claim parsing
  Budget: 100 CHF covers 7,000-10,000 products

**v1 health_wash_score renamed to health_wash_score_v1:**
  Retained in DB as Component A baseline (UPF reality only)
  Replaced by health_wash_score_v3 after vision merge

**False positives eliminated by this change (see OBS-010 to OBS-017):**
  Enriched flour vitamins, milk proteins, natural colorants,
  tautological energy claims, protein-as-ingredient

**References:** docs/DATA_OBSERVATIONS.md OBS-010 through OBS-019

\---



\## Modular contract between pipeline layers



The pipeline is designed so that each layer can be replaced independently without breaking adjacent layers. This is the property that makes v2 and v3 upgrades non-breaking.



```

ingest.py    →  data/raw/\*.json

&#x20;               data/sample/sample\_all\_\*.csv

&#x20;               \[contract: barcode, product fields, additives\_tags]



clean.py     →  data/sample/clean\_\*.csv

&#x20;               \[contract: same columns + cleaned text, language flags,

&#x20;                completeness\_score, nlp\_eligible, primary\_brand,

&#x20;                primary\_country, cluster\_label (null)]



analyze.py   →  data/sample/analyzed\_\*.csv

&#x20;               \[contract: all clean columns + NLP output columns,

&#x20;                health\_wash\_score, health\_wash\_category,

&#x20;                upf\_markers\_found, functional\_claims\_found]



load.py      →  database/functional\_food\_radar.db

&#x20;               data/sample/powerbi\_products\_\*.csv

&#x20;               data/sample/powerbi\_nlp\_\*.csv

&#x20;               \[contract: SQLite schema as defined in DDL\_\* constants]

```



\*\*v2 upgrade (K-Means):\*\* Replace stub in `analyze.py`. No other files change. `cluster\_label` column populates automatically.



\*\*v3 upgrade (LLM vision):\*\* New script `vision.py` reads analyzed CSV, fetches images, extracts claims, writes `claims` table to SQLite. Joins to `nlp\_results` on barcode. No existing scripts change.



\---



\## Known limitations



| Limitation | Impact | Planned fix |

|---|---|---|

| FR language dominance (69%) | NLP misses 16% of products | German in v1.5, bulk export for UK/US |

| Crowdsourced data quality | Variable completeness, some errors | Reality checks in notebooks/, completeness\_score |

| No sales volume data | Can't measure market share | Documented — trend proxy only |

| Brand fragmentation | Conglomerate averages misleading | Company mapping table in v1.5 |

| OFF category folksonomy | Misclassification in query results | Refined with bulk export hierarchy |

| v1 NLP is claim-side blind | Misses front-of-pack claims | v3 LLM vision |

| Sample size (1,348 dev) | Patterns may not hold at scale | 9,000 scale test before v3 |



\---



\## Versioning summary



| Version | Status | Core deliverable |

|---|---|---|

| v1 | ✅ Complete | Rule-based NLP, health-wash score, SQLite, 1,348 products |

| v1.5 | 📋 Planned | German NLP, company mapping, UK/US filtering |

| v2 | ⏸ Deferred | K-Means clustering, scatter plot visuals |

| v3 | 🚀 In progress | LLM vision, claim extraction, claim-reality gap |

| Production | 📋 Planned | Full OFF bulk export, weekly scheduler, Power BI |



\---



\*This document is updated as new decisions are made.\*  

\*Last updated: 20 May 2026\*





