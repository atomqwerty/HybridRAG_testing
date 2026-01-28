
import sys
sys.path.append('app')
from app.database import get_db_connection

graph = get_db_connection()
results = graph.query("MATCH (n) WHERE n.image_path IS NOT NULL RETURN n.image_path as path LIMIT 20")
print("--- RANDOM IMAGE PATHS ---")
for r in results:
    print(r['path'])

print("\n--- WEB IMAGE PATHS ---")
results = graph.query("MATCH (n) WHERE n.image_path CONTAINS 'web_' RETURN n.image_path as path LIMIT 10")
for r in results:
    print(r['path'])
