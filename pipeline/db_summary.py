import sqlite3
conn = sqlite3.connect('database/functional_food_radar.db')
c = conn.cursor()

c.execute('SELECT COUNT(*) FROM products')
print(f'Total products: {c.fetchone()[0]:,}')

c.execute('''SELECT health_wash_category_v1, COUNT(*) as cnt
             FROM nlp_results WHERE health_wash_category_v1 IS NOT NULL
             GROUP BY health_wash_category_v1 ORDER BY cnt DESC''')
print('\nv1 UPF distribution:')
for row in c.fetchall():
    print(f'  {row[0]:<45} {row[1]:,}')

c.execute('''SELECT health_wash_category_v3, COUNT(*) as cnt
             FROM nlp_results WHERE health_wash_category_v3 IS NOT NULL
             GROUP BY health_wash_category_v3 ORDER BY cnt DESC''')
print('\nv3 full score distribution:')
for row in c.fetchall():
    print(f'  {row[0]:<45} {row[1]:,}')

c.execute('''SELECT p.primary_brand,
               AVG(r.health_wash_score_v3) as avg_v3,
               AVG(r.health_wash_score_v1) as avg_v1,
               COUNT(*) as n
             FROM products p JOIN nlp_results r ON p.barcode=r.barcode
             WHERE r.health_wash_score_v3 IS NOT NULL
             GROUP BY p.primary_brand HAVING n >= 20
             ORDER BY avg_v3 DESC LIMIT 20''')
print('\nTop 20 mainstream brands by avg v3 score (min 20 products with vision):')
for row in c.fetchall():
    uplift = row[1] - row[2]
    print(f'  {str(row[0]):<30} v1={row[2]:.1f} -> v3={row[1]:.1f} (+{uplift:.1f}) n={row[3]}')

conn.close()

# Claim type breakdown across v3 sample
import pandas as pd
df = pd.read_csv('data/sample/powerbi_merged_20260524_071111.csv')
print('\nv3 claim type frequency across 4,714 products:')
from collections import Counter
all_claims = []
for claims in df['v3_claims_found'].dropna():
    if claims:
        all_claims.extend(claims.split('|'))
for claim, count in Counter(all_claims).most_common(20):
    pct = count / len(df) * 100
    print(f'  {claim:<35} {count:>5} products ({pct:.1f}%)')

print('\nCombined benefit group frequency:')
benefit_groups = {
    'protein':      ['protein_claim', 'protein_amount_g'],
    'natural':      ['natural_claim', 'no_artificial', 'clean_label_claim', 
                     'no_palm_oil', 'organic_claim', 'bio'],
    'vegan':        ['vegan_claim', 'dairy_free_claim', 'plant_based_claim'],
    'sugar':        ['no_added_sugar', 'reduced_sugar'],
    'energy':       ['energy_claim'],
    'gut':          ['fibre_claim', 'probiotic_claim', 'prebiotic_claim'],
    'fortif':       ['fortification_claim'],
    'sustain':      ['sustainability_halo', 'origin_quality_claim', 
                     'artisan_claim', 'heritage_claim'],
    'reform':       ['reformulation_claim', 'comparative_claim'],
    'glp1':         ['glp1_positioning'],
    'free_from':    ['no_gluten', 'no_lactose'],
}
for group, claims in benefit_groups.items():
    mask = df['v3_claims_found'].apply(
        lambda x: any(c in str(x) for c in claims) if pd.notna(x) else False
    )
    n = mask.sum()
    pct = n / len(df) * 100
    print(f'  {group:<25} {n:>5} products ({pct:.1f}%)')

print('\nBrand x claim group matrix (top mainstream brands):')
target_brands = [
    'special k', "kellogg's", 'kind', 'nature valley', 'actimel',
    'belvita', 'gerble', 'snickers', 'u', 'emmi',
    'danone', 'nestle', 'alpro', 'oatly'
]
benefit_groups = {
    'protein':       ['protein_claim', 'protein_amount_g'],
    'natural':       ['natural_claim', 'no_artificial', 'clean_label_claim', 'no_palm_oil'],
    'sugar':         ['no_added_sugar', 'reduced_sugar'],
    'energy':        ['energy_claim'],
    'gut':           ['fibre_claim', 'probiotic_claim', 'prebiotic_claim'],
    'fortif':        ['fortification_claim'],
    'sustain':       ['sustainability_halo', 'origin_quality_claim', 'artisan_claim'],
    'reform':        ['reformulation_claim', 'comparative_claim'],
}
for brand in target_brands:
    brand_df = df[df['v3_claims_found'].notna() | True]
    brand_df = pd.read_csv('data/sample/powerbi_merged_20260524_071111.csv')
    brand_df = brand_df[brand_df['primary_brand'] == brand]
    total = len(brand_df)
    if total == 0:
        continue
    claim_counts = []
    for group, claims in benefit_groups.items():
        mask = brand_df['v3_claims_found'].apply(
            lambda x: any(c in str(x) for c in claims) if pd.notna(x) else False
        )
        n = mask.sum()
        if n > 0:
            claim_counts.append(f'{group}({n})')
    claims_str = ', '.join(claim_counts) if claim_counts else 'no claims'
    print(f'  {brand:<15} ({total:>2}): {claims_str}')