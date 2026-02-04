"""
Helper script to update keyword_retrieve in run_qa.py with page-level retrieval.
Run this from the project root: python scripts/patch_retrieval.py
"""

import re

def patch_keyword_retrieve():
    file_path = 'app/run_qa.py'
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Find and replace the keyword_retrieve query
    old_query_pattern = r'(query = """[\s\S]*?RETURN full_context as text.*?""")'
    
    new_query = '''query = """
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
    WITH node, score, reduce(s = '', text IN all_texts | s + '\\\\n' + text) as full_page_context
    
    RETURN full_page_context as text, node.source as source, node.page as page, node.image_path as image_path, score
    """'''
    
    # Replace in keyword_retrieve function only (after line ~202)
    # Find the function and its query
    lines = content.split('\n')
    in_function = False
    in_query = False
    new_lines = []
    skip_until_end_query = False
    
    for i, line in enumerate(lines):
        if 'def keyword_retrieve(' in line:
            in_function = True
        
        if in_function and 'query = """' in line and 'chunk_text_index' in lines[i+1] if i+1 < len(lines) else False:
            # Start replacement
            new_lines.append('    ' + new_query.split('\n')[0])
            for qline in new_query.split('\n')[1:]:
                new_lines.append('    ' + qline)
            skip_until_end_query = True
            continue
        
        if skip_until_end_query:
            if '"""' in line and 'query' not in line:
                skip_until_end_query = False
            continue
        
        new_lines.append(line)
    
    with open(file_path, 'w') as f:
        f.write('\n'.join(new_lines))
    
    print("✅ Patched keyword_retrieve function with page-level retrieval")

if __name__ == "__main__":
    patch_keyword_retrieve()
