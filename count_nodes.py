
import sys
sys.path.append('app')
from app.database import get_db_connection

graph = get_db_connection()
count = graph.query("MATCH (n) RETURN count(n) as count")[0]['count']
print(f"Total Nodes in Database: {count}")
