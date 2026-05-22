import sqlite3
conn = sqlite3.connect('database/functional_food_radar.db')
c = conn.cursor()

tier1_brands = [
    'emmi', 'belvita', "kellogg's", 'innocent', 'nakd',
    'alpro', 'oatly', 'chiefs', 'nature valley', 'gerble',
    'gerblé', 'oatly', 'special k', 'nestle', 'danone'
]

print("=== TIER 1 BRAND COVERAGE IN DB ===\n")
for brand in tier1_brands:
    c.execute("""
        SELECT COUNT(*), AVG(r.health_wash_score),
               COUNT(CASE WHEN r.health_wash_score >= 45 THEN 1 END)
        FROM products p
        JOIN nlp_results r ON p.barcode = r.barcode
        WHERE p.primary_brand = ?
    """, (brand,))
    row = c.fetchone()
    count = row[0]
    avg = round(row[1], 1) if row[1] else 0
    medium_plus = row[2]
    status = "OK" if count >= 5 else "LOW" if count > 0 else "MISSING"
    print(f"  {brand:<20} n={count:<6} avg={avg:<6} medium+={medium_plus:<5} [{status}]")

conn.close()