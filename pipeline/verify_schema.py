import sqlite3, sys
sys.path.insert(0, 'pipeline')
from load import NLP_COLS, PRODUCT_COLS
conn = sqlite3.connect('database/functional_food_radar.db')
c = conn.cursor()

c.execute("PRAGMA table_info(nlp_results)")
db_cols = {row[1] for row in c.fetchall()}
code_cols = set(NLP_COLS + ['barcode', 'analyzed_at'])
missing_in_db = code_cols - db_cols
missing_in_code = db_cols - code_cols
if missing_in_db:
    print(f"In NLP_COLS but NOT in DB: {missing_in_db}")
if missing_in_code:
    print(f"In DB but NOT in NLP_COLS: {missing_in_code}")
if not missing_in_db and not missing_in_code:
    print("NLP_COLS and DB schema are in sync")

c.execute("PRAGMA table_info(products)")
db_cols = {row[1] for row in c.fetchall()}
code_cols = set(PRODUCT_COLS + ['barcode', 'ingested_at'])
missing_in_db = code_cols - db_cols
missing_in_code = db_cols - code_cols
if missing_in_db:
    print(f"PRODUCT_COLS in code but NOT in DB: {missing_in_db}")
if missing_in_code:
    print(f"Products DB but NOT in PRODUCT_COLS: {missing_in_code}")
if not missing_in_db and not missing_in_code:
    print("PRODUCT_COLS and DB schema are in sync")
conn.close()