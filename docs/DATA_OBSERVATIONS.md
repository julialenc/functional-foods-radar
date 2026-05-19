Data Observations Log

Functional Food Radar — Running Notes

This file documents data quality findings, analytical observations, and open

questions discovered during pipeline development. It is written for a mixed

audience: data engineers, nutritionists, public health researchers, and people

evaluating this dataset for CPG or startup purposes.

After project completion, sections of this file will be reviewed for inclusion

in the ADR, README, or a project wiki.



What We Actually Pull From Open Food Facts

The OFF API has 180+ fields per product. We deliberately pull only 14:

code, product\_name, brands, categories, ingredients\_text, nutriments, nutriscore\_grade, nova\_group, countries\_tags, labels\_tags, quantity, packaging, created\_t, last\_modified\_t

Implication for readers: Fields not pulled include allergens, additives

list, ecoscore, serving size, packaging materials, certifications, and

photographer credits. These can be added in future versions by extending

the FIELDS parameter in ingest.py. The cleaning and storage pipeline

requires no changes to accommodate new fields.



Observation Log



OBS-001 — French language dominance

Date: 18 May 2026

File: data/sample/sample\_all\_20260518\_104620.csv (300 rows)

Finding:

Language distribution across 286 clean rows:



FR: 197 (69%)

OTHER: 40 (14%)

EN: 32 (11%)

BOTH: 10 (3%)  — bilingual packaging, common in Switzerland/Belgium/Canada

UNKNOWN: 7 (2%)



French dominance is structural, not a sampling accident. OFF was founded

in France and French contributors remain the most active globally.

The 100-row sample showed 80% FR; the full 300-row sample settled at 69%

as later rows included more non-FR products.

Implication for NLP (Option A): Ingredient flagging dictionaries must

cover both EN and FR variants. Translation is not required — most

ultra-processed markers share Latin roots across both languages

(e.g. maltodextrin, lecithine/lecithin, sirop de glucose/glucose syrup).

Implication for public health readers: Coverage is strongest for

Western European markets (France, Belgium, Switzerland). Results should

not be generalised to global markets without caveat.



OBS-002 — Nutritional null rates

Date: 18 May 2026

File: clean\_20260518\_111244.csv (286 rows)

Finding:

FieldMissing%energy\_kcal279%fat\_100g279%saturated\_fat\_100g2910%carbs\_100g269%sugars\_100g2810%fiber\_100g6322%protein\_100g279%salt\_100g186%

Core macros (fat, carbs, protein, sugar) missing \~9% — better than

expected for a crowdsourced database.

fiber\_100g at 22% missing is structurally expected: fiber is the most

commonly omitted nutrient on packaging globally, especially outside the EU

where fiber labelling is not mandatory.

Implication for v2 clustering (Option B): K-Means will need a

strategy for missing nutritional values. Options: drop incomplete rows

(loses \~9% of data), impute with category median (introduces bias),

or cluster only on fields present (requires variable-feature clustering).

Recommended: drop rows missing >2 macro fields for clustering only;

retain all rows in the main dataset.



OBS-003 — Energy outliers (data errors)

Date: 18 May 2026

File: sample\_all\_20260518\_104620.csv

Finding:

2 products had energy\_kcal values of 3833 kcal per 100g.

Maximum physically possible: \~900 kcal/100g (pure fat).

These were capped to NaN by clean.py (Step 7).

Likely cause: Unit entry error — contributor entered kJ value in the

kcal field (3833 kJ ÷ 4.18 = \~917 kcal, still above cap, so likely a

combined entry error).

Implication: Always cap before any nutritional analysis. The cap

values in clean.py (NUTRIMENT\_CAPS) are physically grounded, not

arbitrary.



OBS-004 — Low completeness products cluster around beverages

Date: 18 May 2026

File: clean\_20260518\_111244.csv

Finding:

22 products scored below 50/100 on completeness. The pattern is clear:



Waters (Ain Saïss, Aquafina, Oulmes, Ain Atlas): near-zero nutritional

values, brands don't fill in nutritional fields because they are

essentially zero. Technically correct, structurally incomplete.

Chicory/coffee drinks (Ricoré x3, Leroux, Benco): hot drink category

where serving-based nutrition is more common than per-100g.

Chocolate powders (Nesquik, Poulain x3): similar serving-size issue.

1 barcode-only entry (product\_name = "41022", score = 18): genuine

data garbage, candidate for removal in production.

1 Arabic-script product (العين): valid product, completeness penalised

by language barrier in our keyword-based scoring.



Implication for completeness score metric: The score conflates two

distinct problems: (a) genuinely incomplete data entry, and (b) products

where near-zero values are correct but unfilled. A future version should

handle water/mineral water as a special case.

Implication for "agentic readiness" narrative: Waters scoring low is

misleading — they ARE machine-readable, they just have little to say.

The interesting low-scorers for the health-washing story are the

chocolate powders and processed drinks.



OBS-005 — Nutriscore distribution is health-skewed

Date: 18 May 2026

File: clean\_20260518\_111244.csv

Finding:

GradeCountA74B52C60D36E58

A and B combined (126) outnumber D and E combined (94). This is not

representative of supermarket shelves, where D and E products are

typically more prevalent in snack and beverage categories.

Likely cause: OFF contributor selection bias. Health-conscious people

are more likely to scan and submit products. People buying ultra-processed

snacks are less likely to be OFF contributors.

Implication for health-washing analysis: Trend analysis (claim counts

over time) is more reliable than absolute prevalence estimates. Saying

"High Protein claims grew 340% in 18 months" is defensible. Saying

"30% of snacks are Nutriscore A" is not — it reflects contributor bias,

not market reality.

Implication for v2 clustering: OFF's own Nutriscore grades can serve

as ground truth to validate K-Means clusters. If our clusters don't

broadly align with A/B vs D/E, the clustering needs revision.



OBS-006 — Duplicate barcodes

Date: 18 May 2026

Finding: 14 duplicate barcodes found in 300 raw rows (4.7%).

All dropped on first occurrence kept basis.

Likely cause: Same product appearing in multiple OFF categories

(e.g. a protein bar tagged as both "snacks" and "cereals"). Our query

fetches by category, so cross-category products appear multiple times.

Implication for production pipeline: Deduplication on barcode is

correct and sufficient. In future, consider logging which categories

each barcode appeared in before deduplication — useful for category

overlap analysis.



Open Questions



OQ-001: Should waters be excluded from completeness scoring or scored

separately? Their low scores distort the brand-level completeness

analysis.

OQ-002: The OTHER language group (14%) contains valid nutritional data.

Should we attempt secondary language detection (German, Spanish, Arabic)

for v2, or flag as "NLP-excluded" and document the limitation?

OQ-003: Ricoré appears 3 times with slightly different product names

and barcodes but clearly the same product family. Should we add

brand-family deduplication logic, or is barcode-level correct?

OQ-004: Are there fields in the OFF API we should add for the

health-washing story? Candidates: additives\_tags (pre-parsed list

of E-numbers), allergens\_tags, serving\_size.





Fields Available in OFF But Not Currently Pulled

For reference — these can be added to FIELDS in ingest.py:



additives\_tags — pre-parsed E-number list (very useful for Option A)

allergens\_tags — allergen list

serving\_size — serving size in g/ml

ecoscore\_grade — environmental impact score

ecoscore\_data — detailed environmental breakdown

manufacturing\_places — where made

purchase\_places — where sold

stores — retailer names

image\_url — product image

url — OFF product page URL





This file is updated continuously during development.

Last updated: 18 May 2026



\---



\### OBS-007 — Reality check findings

\*\*Date:\*\* 18 May 2026

\*\*Script:\*\* notebooks/reality\_checks.py



\*\*Check 1 — Calorie plausibility (4 flags):\*\*

\- CRISTALINE water (0 kcal) in snacks: OFF contributor misclassification,

&#x20; not a data error. Calories correct for water.

\- Cranberry/almond cookie (48 kcal/100g): genuine data error. Carrefour

&#x20; confirms 471 kcal/100g. Likely per-serving entry mistake.

\- Nescafe Classic (267 kcal/100g): plausible for instant powder. Flag

&#x20; for manual review, do not drop.

\- Caobel drinking chocolate (366 kcal/100g): correct for chocolate

&#x20; powder. Beverage kcal range too narrow for hot drink powders.



\*\*Check 2 — Sugar vs carbs:\*\* PASS (0 flags)

\*\*Check 3 — Saturated vs total fat:\*\* PASS (0 flags)



\*\*Check 4 — Pack size sanity (2 flags after comma fix):\*\*

\- Coke 0kg: no usable quantity data, candidate for removal in production

\- Al Ain 8L: plausible, sold in 5L gallons in UAE market



\*\*Parser fix applied:\*\* European decimal commas normalised in clean.py

Step 3. Reduced Check 4 flags from 4 to 2.



\*\*Unparseable quantity values (13 rows, not flagged):\*\*

Root cause: spelled-out units in multiple languages:

\- English: "gram", "gr", "grammes", "litres"

\- Arabic: "غ" (gram symbol)

\- Bare numbers with no unit: "250", "230", "500"

Not a data error — parser limitation. Acceptable for v1.



\*\*Overall data quality assessment:\*\*

Checks 2 and 3 passing cleanly (0 flags each) is a strong signal —

the core nutritional relationships are internally consistent across

286 products. Main data quality issues are category misclassification

and quantity field formatting, neither of which affects the NLP or

nutritional analysis.



\---



\### OBS-008 — NLP scope restricted to EN and FR for v1

\*\*Date:\*\* 18 May 2026

\*\*Decision:\*\* nlp\_eligible column added to clean.py (Step 12)



Rows eligible for Option A NLP analysis: EN + FR + BOTH only.

OTHER and UNKNOWN rows retained in dataset for nutritional analysis

but excluded from ingredient flagging.



Coverage: 239 of 286 rows (84%)

Breakdown: FR=197, EN=32, BOTH=10



Excluded (16%): OTHER=40, UNKNOWN=7

OTHER contains: Bulgarian, Arabic, German, Spanish, and other languages.

These rows have valid nutritional data and are included in:

\- Completeness scoring

\- v2 K-Means clustering

\- Power BI nutritional visuals



They are excluded only from Option A ingredient text flagging, where

an EN/FR dictionary would produce silent false negatives.



\*\*How to use in analyze.py:\*\*

&#x20;   eligible = df\[df\["nlp\_eligible"] == True]

&#x20;   # run NLP only on eligible rows



\---



\### OBS-009 — German identified as v1.5 language extension candidate

\*\*Date:\*\* 19 May 2026

\*\*Finding:\*\* Austria = 10 products (3.5% of sample).

German is the third most represented language after FR and EN.

German ingredient vocabulary shares significant overlap with EN/FR

(maltodextrin, lecithin, glucose-sirup, palmöl etc.) making

dictionary extension low-effort and high-accuracy.



\*\*Decision:\*\* Deferred to v1.5 after EN/FR NLP is validated.

Adding before validation risks introducing false positives.

\*\*Action:\*\* Extend ULTRA\_PROCESSED\_MARKERS and FUNCTIONAL\_CLAIM\_MARKERS

in analyze.py with German variants when ready.

\---



\### OBS-010 — NLP dictionary false positives identified and fixed

\*\*Date:\*\* 19 May 2026

\*\*Script:\*\* pipeline/analyze.py

\*\*Finding:\*\* Two false positive patterns found on 286-product validation sample:



1\. curcuma/paprika triggering adaptogen\_claim on Harry's brioche

&#x20;  Root cause: used as natural colorants ("extraits végétaux à pouvoir

&#x20;  colorant"), not as functional supplement claims.

&#x20;  Fix: replaced "curcuma" with "extrait de curcuma" — requires extract

&#x20;  context to fire, not plain colorant use.



2\. fibre de chicorée triggering prebiotic\_claim on Harry's sandwich bread

&#x20;  Root cause: chicory fibre used as texture/bulk ingredient, not marketed

&#x20;  as a prebiotic supplement.

&#x20;  Fix: replaced "chicorée" with specific prebiotic forms only

&#x20;  (inulin de chicorée, extrait de chicorée).



\*\*Lesson:\*\* Always validate NLP dictionary on a small known sample before

scaling. False positives inflate health-wash scores and undermine

credibility of the analysis. The validation loop (run → spot → fix → rerun)

is mandatory before v3 scale-up.



\*\*Remaining risk:\*\* More false positives likely exist in the OTHER language

group (40 products) and will surface when German is added in v1.5.

French products with ingredient-as-colour patterns (saffron, beetroot,

spirulina as colorant) may also trigger adaptogen/fortification flags

incorrectly. Recommend manual review of top 20 scored products before

any public-facing analysis.

