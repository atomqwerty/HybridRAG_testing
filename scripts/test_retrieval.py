
import sys
import os
import argparse

# App context setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

from app.database import get_db_connection
from app.run_qa import keyword_retrieve, vector_retrieve, initialize_reranker
from app.logger import setup_logger

logger = setup_logger("test_retrieval")

def test_retrieval(query):
    print(f"\n🔎 Testing Retrieval for: '{query}'")
    
    try:
        graph = get_db_connection()
        print("✅ DB Connected.")

        # 0. Check Graph Links
        print("\n--- Checking Graph Links ---")
        link_count = graph.query("MATCH ()-[r:NEXT]->() RETURN count(r) as count")[0]['count']
        print(f"🔗 Total ':NEXT' relationships in DB: {link_count}")
        if link_count == 0:
            print("❌ WARNING: No links between chunks found! Table context will be broken.")
        else:
            print("✅ Chunk linking confirmed.")
        
        # 1. Keyword Search
        print("\n--- Keyword Search Results ---")
        kw_results = keyword_retrieve(graph, query, k=3)
        if kw_results:
            for i, res in enumerate(kw_results):
                # Print full text to see context stitching
                print(f"\n[{i+1}] Score: {res['score']:.4f} | Source: {res.get('source')}")
                print(f"    🖼️ Image Path: {res.get('image_path')}")
                print(f"    Text Preview (len={len(res['text'])}): {res['text'][:300].replace(chr(10), ' ')}...")
                if len(res['text']) > 500: # Assumption: Single chunk < 500 usually
                     print("    ✅ Likely Stitched Context (Text is long)")
        else:
            print("❌ No keyword matches found.")

        # 2. Vector Search (Optional, if embeddings are working)
        # We need an embedding model for this.
        # This script assumes run_qa.py logic works.
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Retrieval")
    parser.add_argument("query", nargs="?", default="บริษัทย่อย", help="Search query (default: 'บริษัทย่อย')")
    args = parser.parse_args()
    
    test_retrieval(args.query)
