import os
import sqlite3
import json
import time
import pandas as pd
import numpy as np
from datetime import datetime
from pymongo import MongoClient

# ==========================================
# SETUP & RELATIVE PATH CONFIGURATION
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LANDING_DIR = os.path.join(BASE_DIR, "landing_zone")
os.makedirs(LANDING_DIR, exist_ok=True)

CSV_FILE_PATH = os.path.join(BASE_DIR, "warehouse_messy_data.csv")
JSON_FILE_PATH = os.path.join(LANDING_DIR, "raw_feedback_logs.json")
SQLITE_DB_PATH = os.path.join(BASE_DIR, "retail_warehouse.db")

# Setup MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = "retail_warehouse_db"
MONGO_COLLECTION_NAME = "sales_documents"


def create_mock_json_logs(num_records=1200):
    """Generates mock customer feedback JSON logs if none exist."""
    if not os.path.exists(JSON_FILE_PATH):
        feedback_data = []
        for i in range(1, num_records + 1):
            feedback_data.append({
                "transaction_id": i,
                "customer_feedback": {
                    "rating": np.random.randint(1, 6),
                    "review": np.random.choice(["Great item!", "Slow shipping", "Satisfied", "Poor quality", "Excellent"]),
                    "tags": list(np.random.choice(["fast-shipping", "quality", "value", "support"], size=2, replace=False))
                },
                "device_info": {
                    "os": np.random.choice(["iOS", "Android", "Windows", "MacOS"]),
                    "ip": f"192.168.1.{np.random.randint(1, 255)}"
                }
            })
        with open(JSON_FILE_PATH, 'w') as f:
            json.dump(feedback_data, f)


def run_etl_pipeline():
    start_time = time.time()
    
    # Generate mock JSON payload to pair with raw CSV
    create_mock_json_logs()

    # ==========================================
    # 1. PHASE 1: EXTRACTION
    # ==========================================
    if not os.path.exists(CSV_FILE_PATH):
        raise FileNotFoundError(f"Source CSV not found at {CSV_FILE_PATH}")

    # Load CSV and JSON
    df_raw_csv = pd.read_csv(CSV_FILE_PATH)
    with open(JSON_FILE_PATH, 'r') as f:
        raw_json_data = json.load(f)
    
    raw_csv_count = len(df_raw_csv)
    raw_json_count = len(raw_json_data)
    
    print(f"[EXTRACT] Successfully read {raw_csv_count:,} raw rows from CSV and {raw_json_count:,} objects from JSON.")

    # ==========================================
    # 2. PHASE 2: TRANSFORMATION & CLEANSING
    # ==========================================
    df_clean = df_raw_csv.copy()

    # A. Deduplication
    initial_rows = len(df_clean)
    df_clean = df_clean.drop_duplicates()
    dropped_duplicates = initial_rows - len(df_clean)

    # B. Missing Values / ID Imputation
    if 'customer_id' in df_clean.columns:
        df_clean['customer_id'] = df_clean['customer_id'].fillna("UNKNOWN_CUST")
    
    # C. Date Standardization to ISO 8601 (YYYY-MM-DD)
    date_cols = [c for c in df_clean.columns if 'date' in c.lower() or 'time' in c.lower()]
    for d_col in date_cols:
        df_clean[d_col] = pd.to_datetime(df_clean[d_col], errors='coerce').dt.strftime('%Y-%m-%d')
        df_clean[d_col] = df_clean[d_col].fillna(datetime.now().strftime('%Y-%m-%d'))

    # D. Numeric Casts & Handling Anomalies
    num_cols = df_clean.select_dtypes(include=[np.number]).columns
    for col in num_cols:
        df_clean[col] = df_clean[col].fillna(0)

    # Reshape JSON into a Lookup Map for MongoDB merging
    json_lookup = {item['transaction_id']: item for item in raw_json_data if 'transaction_id' in item}

    # Prepare nested documents for MongoDB payload
    mongo_documents = []
    for idx, row in df_clean.iterrows():
        tx_id = row.get('transaction_id', idx)
        doc = row.to_dict()
        
        # Merge nested feedback metadata if transaction_id matches
        if tx_id in json_lookup:
            doc['feedback'] = json_lookup[tx_id].get('customer_feedback')
            doc['device_info'] = json_lookup[tx_id].get('device_info')
        else:
            doc['feedback'] = None
            doc['device_info'] = None

        mongo_documents.append(doc)

    print(f"[TRANSFORM] Dropped {dropped_duplicates} duplicate rows. Standardized dates and imputed missing customer values. Reshaped structures.")

    # ==========================================
    # 3. PHASE 3: DUAL-TARGET LOADING
    # ==========================================
    
    # --- A. LOAD TO SQLITE ---
    conn_sqlite = sqlite3.connect(SQLITE_DB_PATH)
    
    # Split into Relational Tables: fact_sales and dim_store
    store_cols = [c for c in df_clean.columns if 'store' in c.lower() or 'location' in c.lower()]
    if store_cols:
        dim_store = df_clean[store_cols].drop_duplicates().reset_index(drop=True)
        dim_store.to_sql('dim_store', conn_sqlite, if_exists='replace', index=False)
    
    df_clean.to_sql('fact_sales', conn_sqlite, if_exists='replace', index=False)
    sqlite_inserted = len(df_clean)
    conn_sqlite.close()

    print(f"[LOAD - SQLITE] Successfully inserted {sqlite_inserted:,} rows into SQLite table 'fact_sales'.")

    # --- B. LOAD TO MONGODB ---
    mongo_inserted = 0
    try:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        mongo_db = mongo_client[MONGO_DB_NAME]
        mongo_coll = mongo_db[MONGO_COLLECTION_NAME]
        
        # Clear collection and insert cleaned nested records
        mongo_coll.delete_many({})
        if mongo_documents:
            result = mongo_coll.insert_many(mongo_documents)
            mongo_inserted = len(result.inserted_ids)
        
        print(f"[LOAD - MONGODB] Successfully inserted {mongo_inserted:,} documents into collection '{MONGO_DB_NAME}.{MONGO_COLLECTION_NAME}'.")
    except Exception as e:
        print(f"[LOAD - MONGODB WARNING] Could not connect to local MongoDB instance: {e}")
        print("[LOAD - MONGODB WARNING] (Skipping live MongoDB load. Ensure MongoDB service is running on port 27017).")

    # ==========================================
    # AUDIT COMPLETE
    # ==========================================
    elapsed_time = round(time.time() - start_time, 2)
    print(f"[COMPLETE] Multi-target pipeline execution finished successfully in {elapsed_time} seconds.")


if __name__ == "__main__":
    run_etl_pipeline()