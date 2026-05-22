import sqlite3, pandas as pd
conn = sqlite3.connect('database/functional_food_radar.db')

brands_to_check = ['totinos', 'little debbie', 'pop-tarts', 'hostess']

for brand in brands_to_check:
    df = pd.read_sql(f"""
        SELECT p.product_name, p.query_category,
               r.health_wash_score, r.upf_markers_found,
               r.functional_claims_found, r.negative_claims_found
        FROM products p
        JOIN nlp_results r ON p.barcode = r.barcode
        WHERE p.primary_brand = '{brand}'
        AND r.health_wash_score >= 60
        ORDER BY r.health_wash_score DESC
        LIMIT 5
    """, conn)
    print(f"\n=== {brand.upper()} (top scorers) ===")
    pd.set_option('display.max_colwidth', 40)
    print(df.to_string())

conn.close()