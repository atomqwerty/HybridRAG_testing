import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

from app.database import get_db_connection

def check_table_distribution():
    """Check how the table chunks are distributed across pages."""
    graph = get_db_connection()
    
    # Find chunks mentioning 'กรรมการ'
    query = """
    MATCH (c:Chunk)
    WHERE c.text CONTAINS 'กรรมการ'
    RETURN c.source as source, c.page as page, c.seq as seq, 
           substring(c.text, 0, 100) as preview
    ORDER BY c.source, c.page, c.seq
    LIMIT 20
    """
    
    results = graph.query(query)
    
    print("\n📊 Distribution of chunks containing 'กรรมการ':\n")
    for r in results:
        print(f"Page {r['page']}, Seq {r['seq']}: {r['preview']}...")
    
    # Count chunks per page
    count_query = """
    MATCH (c:Chunk)
    WHERE c.source = 'รายงานประจำปี 2567 บมจ scb.PDF'
    RETURN c.page as page, count(c) as chunk_count
    ORDER BY c.page
    """
    
    counts = graph.query(count_query)
    print("\n📄 Chunks per page:")
    for c in counts:
        print(f"  Page {c['page']}: {c['chunk_count']} chunks")

if __name__ == "__main__":
    check_table_distribution()
