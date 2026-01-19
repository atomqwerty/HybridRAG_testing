from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

URI = os.getenv("NEO4J_URI")
AUTH = (os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))

query = """
MATCH (n:Chunk) 
WHERE n.source ENDS WITH '.pdf' OR n.source ENDS WITH '.PDF'
RETURN DISTINCT n.source as source
LIMIT 100
"""

try:
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            result = session.run(query)
            files = [r["source"] for r in result]
            print(f"Found {len(files)} PDF files:")
            for f in files:
                print(f" - {f}")
except Exception as e:
    print(f"Error: {e}")
