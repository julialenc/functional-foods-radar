import sqlite3, pandas as pd
conn = sqlite3.connect('database/functional_food_radar.db')

# Check what triggers adaptogen_claim on pop-tarts
df = pd.read_sql("""
    SELECT p.product_name, p.ingredients_text,
           r.functional_claims_found, r.upf_markers_found
    FROM products p JOIN nlp_results r ON p.barcode=r.barcode
    WHERE p.primary_brand = 'pop-tarts'
    AND r.functional_claims_found LIKE '%adaptogen%'
    LIMIT 3
""", conn)
print("=== POP-TARTS adaptogen triggers ===")
for _, row in df.iterrows():
    print(f"\nProduct: {row['product_name']}")
    print(f"Claims:  {row['functional_claims_found']}")
    print(f"Ingredients: {str(row['ingredients_text'])[:300]}")

# Check what triggers protein_claim on hostess
df2 = pd.read_sql("""
    SELECT p.product_name, p.ingredients_text,
           r.functional_claims_found
    FROM products p JOIN nlp_results r ON p.barcode=r.barcode
    WHERE p.primary_brand = 'hostess'
    AND r.functional_claims_found LIKE '%protein%'
    LIMIT 3
""", conn)
print("\n\n=== HOSTESS protein triggers ===")
for _, row in df2.iterrows():
    print(f"\nProduct: {row['product_name']}")
    print(f"Claims:  {row['functional_claims_found']}")
    print(f"Ingredients: {str(row['ingredients_text'])[:300]}")

conn.close()