import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pipeline"))
import pandas as pd
import sqlite3
from load import (init_db, load_products, load_nlp_results,
                  compute_weekly_brand_summary, export_powerbi_csvs,
                  log_run, DB_PATH, SAMPLE_DIR)

timestamp = "20260522_001753"
path = os.path.join(SAMPLE_DIR, f"bulk_analyzed_{timestamp}.csv")
print(f"Loading {path}")
df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False,
                 dtype={"barcode": str})
print(f"Rows: {len(df):,}")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA foreign_keys=ON;")
init_db(conn)
p_ins, p_upd = load_products(df, conn, timestamp)
print(f"Products: {p_ins:,} inserted, {p_upd:,} updated")
n_ins, n_upd = load_nlp_results(df, conn, timestamp)
print(f"NLP: {n_ins:,} inserted, {n_upd:,} updated")
compute_weekly_brand_summary(df, conn, timestamp)
export_powerbi_csvs(df, timestamp)
log_run(conn, timestamp, path, len(df), p_ins, p_upd, n_ins, n_upd, "success", "bulk_direct")
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM products")
print(f"Total in DB: {cursor.fetchone()[0]:,}")
conn.close()
print("Done.")