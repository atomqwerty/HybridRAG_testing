import sys
import os
import csv
import re
from neo4j import GraphDatabase

# Add parent path to sys path to import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from app.config import Config

# Using the NEO4J_URI from config
URI = Config.NEO4J_URI
AUTH = (Config.NEO4J_USERNAME, Config.NEO4J_PASSWORD)

def extract_specs_to_csv():
    print(f"Connecting to Neo4j at {URI}...")
    try:
        driver = GraphDatabase.driver(URI, auth=AUTH)
        
        # Query to extract car models and their properties
        # This is a heuristic query assuming we have 'Car' labels or similar structure
        # If not, we scan for nodes that have "price", "battery", "range" in their text or properties
        
        # Since our current graph is unstructured text chunks, we have to be clever.
        # We will look for CHUNK nodes that mention "Price", "Battery", "Range" and try to extract structured data via Regex.
        # OR better: usage of existing structured nodes if available.
        
        # Let's assume we want to BUILD a clean CSV for the Table Agent.
        # We will query all chunks, and use a simple regex to extract data.
        
        query = """
        MATCH (c:Chunk)
        WHERE c.text CONTAINS 'Price' OR c.text CONTAINS 'Battery' OR c.text CONTAINS 'Range' OR c.text CONTAINS 'km'
        RETURN c.text as text, c.source as source
        """
        
        records, summary, keys = driver.execute_query(query)
        print(f"Found {len(records)} potential spec chunks.")
        
        data = []
        
        for record in records:
            text = record['text']
            source = record['source']
            filename = os.path.basename(source)
            
            # Simple Regex Extraction (Heuristic)
            model_match = re.search(r"(BYD|MG|Tesla|ORA|Neta|Deepal|Zeekr|Volvo|BMW|Mercedes)[\w\s\d]*", text, re.IGNORECASE)
            model = model_match.group(0).strip() if model_match else "Unknown"
            
            price_match = re.search(r"(\d{1,3}(?:,\d{3})*)[\s]*(?:Baht|THB|บาท)", text, re.IGNORECASE)
            price = price_match.group(1).replace(',', '') if price_match else None
            
            # Battery in kWh
            batt_match = re.search(r"(\d+(?:\.\d+)?)[\s]*kWh", text, re.IGNORECASE)
            battery = batt_match.group(1) if batt_match else None
            
            # Range in km (NEDC/WLTP)
            range_match = re.search(r"(\d{3,4})[\s]*km", text, re.IGNORECASE)
            range_km = range_match.group(1) if range_match else None
            
            if model != "Unknown" and (price or battery or range_km):
                data.append({
                    "Model": model,
                    "Price (THB)": price,
                    "Battery (kWh)": battery,
                    "Range (km)": range_km,
                    "Source": filename
                })
        
        # Remove duplicates (group by Model and take best non-nulls)
        # For simplicity, just write all non-empty rows
        
        output_file = 'data/specs.csv'
        fieldnames = ["Model", "Price (THB)", "Battery (kWh)", "Range (km)", "Source"]
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
            
        print(f"Successfully exported {len(data)} rows to {output_file}")
        driver.close()
        
    except Exception as e:
        print(f"Extraction failed: {e}")

if __name__ == "__main__":
    extract_specs_to_csv()
