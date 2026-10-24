from pymongo import MongoClient
import json

client = MongoClient("mongodb://localhost:27017/")
db = client["retail_warehouse_db"]
collection = db["sales_documents"]

# Retrieve one nested document as proof
sample_document = collection.find_one({}, {"_id": 0})
print("--- MongoDB Nested Document Verification ---")
print(json.dumps(sample_document, indent=2, default=str))

print(f"\nTotal Documents in MongoDB Collection: {collection.count_documents({})}")