import requests
import json
import time

# Configuration for your RAG API
API_URL = "http://localhost:8080/api/crawl"
# If running inside another container on the same network, use the container name:
# API_URL = "http://hybrid_rag_app:8000/api/crawl"

def trigger_crawl(url, strategy="dlt"):
    """
    Triggers the RAG crawler for a given URL.
    Args:
        url (str): The URL to crawl (e.g., https://example.com).
        strategy (str): 'dlt' (deep crawl) or 'native' (if implemented).
    """
    payload = {
        "url": url,
        "strategy": strategy
    }
    
    try:
        print(f"🚀 Triggering crawl for: {url}...")
        response = requests.post(API_URL, json=payload, timeout=600) # Long timeout for deep crawls
        
        if response.status_code == 200:
            print("✅ Crawl Success:", response.json())
        else:
            print(f"❌ Crawl Failed ({response.status_code}):", response.text)
            
    except Exception as e:
        print(f"⚠️ Connection Error: {e}")

if __name__ == "__main__":
    # Example usage
    target_url = "https://example.com"
    trigger_crawl(target_url)
