import json
import os
from pathlib import Path
from urllib.parse import urlparse

CONFIG_PATH = "data/source_config.json"
DATA_DIR = "data"
URLS_FILE = "data/urls.txt"

def trust_all():
    print("🔓 Trusting all existing data...")
    
    # Load Config
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
    else:
        config = {"strict_mode": True, "rules": [], "default_score": 0.5}
    
    rules = config.get("rules", [])
    existing_patterns = {r['pattern'] for r in rules}
    
    # 1. Trust PDFs
    count_files = 0
    for f in os.listdir(DATA_DIR):
        if f.lower().endswith('.pdf'):
            if f not in existing_patterns:
                rules.append({"pattern": f, "score": 1.0, "type": "file"})
                existing_patterns.add(f)
                count_files += 1
                
    # 2. Trust URLs
    count_urls = 0
    if os.path.exists(URLS_FILE):
        with open(URLS_FILE, "r") as f:
            for line in f:
                url = line.strip()
                if not url or url.startswith('#'): continue
                
                # Extract domain
                try:
                    domain = urlparse(url).netloc.replace('www.', '')
                    if domain and domain not in existing_patterns:
                        rules.append({"pattern": domain, "score": 1.0, "type": "domain"})
                        existing_patterns.add(domain)
                        count_urls += 1
                except: pass

    config['rules'] = rules
    
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)
        
    print(f"✅ trusted {count_files} files and {count_urls} domains.")
    print("Now run ingestion to process them!")

if __name__ == "__main__":
    trust_all()
