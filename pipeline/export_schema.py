import sqlite3
conn = sqlite3.connect('database/functional_food_radar.db')
schema = conn.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()
with open('database/schema.sql', 'w') as f:
    for row in schema:
        if row[0]:
            f.write(row[0] + ';\n\n')
print("schema.sql updated")
conn.close()