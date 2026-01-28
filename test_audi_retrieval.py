
import os
import sys
sys.path.append('app')
from dotenv import load_dotenv
load_dotenv()

from app.run_qa import get_graph, embeddings, vector_retrieve, keyword_retrieve
from app.config import Config

graph = get_graph()
question = "Audi e-tron Sportback 55"

print(f"--- Testing Retrieval for: '{question}' ---")

# 1. Vector Search
print("\n[VECTOR SEARCH]")
try:
    results = vector_retrieve(graph, embeddings, question, k=5, min_score=0.1)
    if results:
        r = results[0]
        print(f"TOP RESULT:\nImage Path: {r.get('image_path')}\nText: {r['text'][:200]}...\nSource: {r.get('source')}")
    else:
        print("No results.")
except Exception as e:
    print(f"ERROR: {e}")

# 2. Keyword Search
print("\n[KEYWORD SEARCH]")
try:
    results = keyword_retrieve(graph, question, k=5)
    if results:
        r = results[0]
        print(f"TOP RESULT:\nImage Path: {r.get('image_path')}\nText: {r['text'][:200]}...\nSource: {r.get('source')}")
    else:
        print("No results.")
except Exception as e:
    print(f"ERROR: {e}")
