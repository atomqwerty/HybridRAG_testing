from database import get_db_connection
import os

try:
    graph = get_db_connection()
    query = """
    MATCH (c:Chunk) 
    WHERE c.source ENDS WITH '.png' OR c.source ENDS WITH '.jpg' OR c.source ENDS WITH '.jpeg'
    RETURN count(c) as count, collect(c.source)[..5] as examples
    """
    res = graph.query(query)
    print("📸 Image Diagnosis:")
    print(res)
except Exception as e:
    print(f"Error: {e}")
