import os
import sqlite3
import pandas as pd

# Derive the directory path relative to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "retail_warehouse.db")

conn = sqlite3.connect(DB_PATH)

# Query fact_sales table
fact_df = pd.read_sql_query("SELECT * FROM fact_sales LIMIT 5;", conn)
print("--- SQLite 'fact_sales' Preview ---")
print(fact_df)

# Check total row count
count = conn.execute("SELECT COUNT(*) FROM fact_sales;").fetchone()[0]
print(f"\nTotal Records in SQLite: {count}")

conn.close()