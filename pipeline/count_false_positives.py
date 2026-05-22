import sqlite3
conn = sqlite3.connect('database/functional_food_radar.db')
c = conn.cursor()

print("=== FALSE POSITIVE SCALE CHECK ===\n")

# How many products score HIGH but are in US market?
c.execute("""
    SELECT COUNT(*) FROM products p
    JOIN nlp_results r ON p.barcode=r.barcode
    WHERE r.health_wash_score >= 70
    AND p.primary_country LIKE '%United States%'
""")
print(f"HIGH score (>=70) US products: {c.fetchone()[0]:,}")

# How many have ONLY fortification_claim (likely enriched flour FP)
c.execute("""
    SELECT COUNT(*) FROM nlp_results
    WHERE functional_claims_found = 'fortification_claim'
    AND health_wash_score >= 45
""")
print(f"MEDIUM+ with ONLY fortification_claim: {c.fetchone()[0]:,}")

# How many have adaptogen_claim
c.execute("""
    SELECT COUNT(*) FROM nlp_results
    WHERE functional_claims_found LIKE '%adaptogen%'
""")
print(f"Products with adaptogen_claim: {c.fetchone()[0]:,}")

# Top adaptogen triggers - what ingredients contain adaptogen keywords
c.execute("""
    SELECT p.ingredients_text FROM products p
    JOIN nlp_results r ON p.barcode=r.barcode
    WHERE r.functional_claims_found LIKE '%adaptogen%'
    AND p.ingredients_lang = 'EN'
    LIMIT 5
""")
print("\nSample EN ingredients triggering adaptogen_claim:")
for row in c.fetchall():
    print(f"  {str(row[0])[:150]}")

conn.close()