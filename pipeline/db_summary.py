import sqlite3
conn = sqlite3.connect('database/functional_food_radar.db')
c = conn.cursor()

c.execute('SELECT COUNT(*) FROM products')
print(f'Total products: {c.fetchone()[0]:,}')

c.execute('''SELECT health_wash_category, COUNT(*) as cnt
             FROM nlp_results WHERE health_wash_category IS NOT NULL
             GROUP BY health_wash_category ORDER BY cnt DESC''')
print('\nHealth-wash distribution:')
for row in c.fetchall():
    print(f'  {row[0]:<45} {row[1]:,}')

c.execute('''SELECT primary_brand, AVG(health_wash_score) as avg, COUNT(*) as n
             FROM products p JOIN nlp_results r ON p.barcode=r.barcode
             WHERE r.health_wash_score IS NOT NULL
             GROUP BY primary_brand HAVING n >= 20
             ORDER BY avg DESC LIMIT 15''')
print('\nTop 15 brands by avg health-wash score (min 20 products):')
for row in c.fetchall():
    print(f'  {str(row[0]):<35} avg={row[1]:.1f}  n={row[2]}')

conn.close()