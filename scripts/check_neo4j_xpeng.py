
import os
import sys
from langchain_community.graphs import Neo4jGraph

# Add project root to sys path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.config import Config

def check_xpeng():
    graph = Neo4jGraph(
        url=Config.NEO4J_URI,
        username=Config.NEO4J_USERNAME,
        password=Config.NEO4J_PASSWORD
    )
    
    print("\n--- [NEO4J] SEARCING FOR XPENG DATA ---\n")
    
    # 1. Search for Entity nodes containing Xpeng
    print("1. Searching for Entity nodes...")
    entities = graph.query("""
        MATCH (n:Entity)
        WHERE n.id CONTAINS 'Xpeng' OR n.id CONTAINS 'G6'
        RETURN n.id, n.type
    """)
    for e in entities:
        print(f"   - Entity: {e['n.id']} ({e['n.type']})")
        
    # 2. Search for Car nodes
    print("\n2. Searching for Car nodes...")
    cars = graph.query("""
        MATCH (c:Car)
        WHERE c.source_url CONTAINS 'xpeng'
        RETURN c.model, c.brand, c.source_url
    """)
    for c in cars:
        print(f"   - Car: {c.get('c.model')} Brand: {c.get('c.brand')} URL: {c['c.source_url']}")
        
    # 3. Search for Chunks containing Xpeng
    print("\n3. Searching for Chunk content...")
    chunks = graph.query("""
        MATCH (c:Chunk)
        WHERE c.text CONTAINS 'Xpeng' AND (c.text CONTAINS 'Long Range' OR c.text CONTAINS 'Standard')
        RETURN c.source, c.page, c.image_path, c.modality, substring(c.text, 0, 100) as preview
        LIMIT 10
    """)
    for ck in chunks:
        print(f"   - Chunk Source: {ck['c.source']} Page: {ck['c.page']} Image: {ck['c.image_path']} Modality: {ck['c.modality']}")
        print(f"     Preview: {ck['preview']}...")

if __name__ == "__main__":
    check_xpeng()
