import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

from app.database import get_db_connection
from app.run_qa import preprocess_thai_query

def test_keyword_query():
    """Test the actual keyword query to see what's returned."""
    graph = get_db_connection()
    
    question = "จากข้อมูลคณะกรรมการและผู้มีอํานาจควบคุมบริษัทรายบุคคล (7.2.2) รายชื่อกรรมการชุดปัจจุบันมีใครบ้าง"
    
    # Apply Thai preprocessing
    question = preprocess_thai_query(question)
    print(f"Preprocessed: {question}\n")
    
    # Build lucene query
    import re
    clean_q = re.sub(r'[+\-&|!(){}\\[\\]^"~*?:\\\\/]', ' ', question)
    terms = clean_q.split()
    lucene_query = " OR ".join([f"{t}~" for t in terms if len(t) > 1])
    print(f"Lucene Query: {lucene_query}\n")
    
    # Run the actual query from run_qa.py
    query = """
        CALL db.index.fulltext.queryNodes("chunk_text_index", $query, {limit: $k})
        YIELD node, score
        
        // --- Page-Level Retrieval: Get ALL chunks from the same page ---
        MATCH (page_chunk:Chunk)
        WHERE page_chunk.source = node.source 
          AND page_chunk.page = node.page
        WITH node, score, collect(page_chunk) as page_chunks
        
        // Sort by sequence
        UNWIND page_chunks as chunk
        WITH node, score, chunk
        ORDER BY chunk.seq
        
        // Concatenate
        WITH node, score, collect(chunk.text) as all_texts
        WITH node, score, reduce(s = '', text IN all_texts | s + '\\n' + text) as full_page_context
        
        RETURN full_page_context as text, node.source as source, node.page as page, node.image_path as image_path, score
        """
    
    results = graph.query(query, {"query": lucene_query, "k": 15})
    
    print(f"Number of results: {len(results)}\n")
    
    for i, r in enumerate(results[:3]):
        print(f"\n=== Result {i+1} ===")
        print(f"Source: {r['source']}")
        print(f"Page: {r['page']}")
        print(f"Score: {r['score']}")
        print(f"Text length: {len(r['text'])} chars")
        print(f"Text preview: {r['text'][:500]}...")
        
        # Count occurrences of "กรรมการ" in the text
        count = r['text'].count('กรรมการ')
        print(f"Occurrences of 'กรรมการ': {count}")

if __name__ == "__main__":
    test_keyword_query()
