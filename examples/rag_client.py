import requests
import json
import os
from typing import Generator, Dict, Any, Union

class RAGClient:
    """
    A Python Client for the Hybrid RAG API.
    Copy this class into your other project to easily interact with the RAG system.
    """
    
    
    def __init__(self, base_url: str = "http://localhost:8080"):
        # DOCKER NOTE:
        # If running from another container on the SAME network, use: "http://hybrid_rag_app:8000"
        # If running from another container EXTERNALLY, use host IP: "http://172.17.0.1:8080"
        self.base_url = base_url.rstrip('/')
        self.api_url = f"{self.base_url}/api"

    def chat(self, message: str, stream: bool = False) -> Union[Dict, Generator]:
        """
        Sends a message to the RAG Chat API.
        Args:
            message: The user's query.
            stream: If True, returns a generator yielding response chunks.
        """
        endpoint = f"{self.api_url}/chat/stream" if stream else f"{self.api_url}/chat"
        payload = {"message": message}
        
        try:
            response = requests.post(endpoint, json=payload, stream=stream)
            response.raise_for_status()
            
            if stream:
                return self._stream_response(response)
            else:
                return response.json()
        except Exception as e:
            print(f"❌ Chat Error: {e}")
            return {}

    def _stream_response(self, response):
        """Helper to yield lines from streaming response."""
        for line in response.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                try:
                    yield json.loads(decoded)
                except:
                    yield decoded

    def crawl(self, url: str) -> Dict[str, Any]:
        """
        Triggers the Web Crawler for a specific URL.
        """
        endpoint = f"{self.api_url}/crawl"
        payload = {"url": url, "strategy": "dlt"}
        
        try:
            print(f"🚀 Triggering Crawler for {url}...")
            response = requests.post(endpoint, json=payload, timeout=600)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ Crawl Error: {e}")
            return {"error": str(e)}

    def upload_file(self, file_path: str, strategy: str = "dlt") -> Dict[str, Any]:
        """
        Uploads a file to the RAG system for ingestion.
        """
        endpoint = f"{self.api_url}/upload"
        
        if not os.path.exists(file_path):
            return {"error": "File not found"}
            
        try:
            print(f"🚀 Uploading {file_path}...")
            with open(file_path, 'rb') as f:
                files = {'file': f}
                data = {'strategy': strategy}
                response = requests.post(endpoint, files=files, data=data)
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ Upload Error: {e}")
            return {"error": str(e)}

if __name__ == "__main__":
    # === Usage Example ===
    client = RAGClient(base_url="http://localhost:8080")
    
    # 1. Test Chat
    print("\n--- Chat Test ---")
    resp = client.chat("Hello!")
    print("Response:", resp.get("result", "No result"))
    
    # 2. Test Crawl (Uncomment to test)
    # print("\n--- Crawl Test ---")
    # print(client.crawl("https://example.com"))
