
import os
import sys
from langchain_community.graphs import Neo4jGraph

# Add project root to sys path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.config import Config

def check_images():
    graph = Neo4jGraph(
        url=Config.NEO4J_URI,
        username=Config.NEO4J_USERNAME,
        password=Config.NEO4J_PASSWORD
    )
    
    # 1. Check for any Chunk with image_path
    print("1. Chunks with image_path:")
    res = graph.query("""
        MATCH (c:Chunk)
        WHERE c.image_path IS NOT NULL AND c.image_path <> ''
        RETURN c.id, c.image_path, c.source, c.page
        LIMIT 5
    """)
    for r in res:
        print(f"   - ID: {r['c.id']} Image: {r['c.image_path']} Source: {r['c.source']} Page: {r['c.page']}")

    # 2. Check specifically for XPENG chunks
    print("\n2. XPENG Chunks with image_path:")
    res = graph.query("""
        MATCH (c:Chunk)
        WHERE (c.text CONTAINS 'Xpeng' OR c.source CONTAINS 'xpeng')
          AND c.image_path IS NOT NULL AND c.image_path <> ''
        RETURN c.id, c.image_path, c.source, c.page
        LIMIT 5
    """)
    for r in res:
        print(f"   - ID: {r['c.id']} Image: {r['c.image_path']} Source: {r['c.source']} Page: {r['c.page']}")

if __name__ == "__main__":
    check_images()
