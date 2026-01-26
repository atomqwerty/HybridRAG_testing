
import os
import time
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph

# Load env variables if not already loaded (safe to call multiple times)
load_dotenv()

def get_db_connection():
    """
    Establishes and returns a connection to the Neo4j database 
    using variables from .env.
    """
    neo4j_uri = os.getenv('NEO4J_URI')
    neo4j_user = os.getenv('NEO4J_USERNAME')
    neo4j_password = os.getenv('NEO4J_PASSWORD')
    
    if not neo4j_uri:
        raise ValueError("NEO4J_URI not found in environment variables")
        
    return Neo4jGraph(
        url=neo4j_uri,
        username=neo4j_user,
        password=neo4j_password
    )

def create_vector_index(graph, dimensions=3072):
    """
    Creates the vector index for chunks if it doesn't exist.
    """
    print(f"   Using embedding dimension: {dimensions}")
    
    # 1. Chunk Index
    try:
        # Check if index exists first? Neo4j 5.x IF NOT EXISTS works well.
        # But if dimension changes, we might need to drop and recreate.
        # For now, we assume user cleans DB if switching models.
        
        graph.query(f"""
        CREATE VECTOR INDEX chunk_vector_index IF NOT EXISTS
        FOR (c:Chunk) ON (c.embedding)
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {dimensions},
            `vector.similarity_function`: 'cosine'
        }}}}
        """)
        print("   ✅ Vector index 'chunk_vector_index' ensured.")
    except Exception as e:
        print(f"   ⚠️ Could not create vector index: {e}")

def create_fulltext_index(graph):
    """
    Creates fulltext indexes for Entity nodes for better keyword search.
    Used by Retrieval QA.
    """
    try:
        graph.query("""
            CREATE FULLTEXT INDEX entity_id_index IF NOT EXISTS 
            FOR (n:Entity) ON EACH [n.id]
        """)
        print("   ✅ Fulltext Index 'entity_id_index' ensured.")
    except Exception as e:
        print(f"   ⚠️ Could not create fulltext index: {e}")

def create_constraints(graph):
    """
    Creates uniqueness constraints to prevent duplicates.
    """
    try:
        # Constraint: Chunk ID must be unique
        graph.query("CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE")
        print("   ✅ Constraint 'chunk_id_unique' ensured.")
        
        # Constraint: Document source uniqueness? 
        # (Optional, but good for tracking)
    except Exception as e:
        print(f"   ⚠️ Could not create constraints: {e}")

def get_existing_sources(graph):
    """
    Queries Neo4j to find all files/URLs that have already been ingested.
    Returns a set of source strings (e.g. 'file.pdf', 'https://example.com').
    """
    try:
        data = graph.query("MATCH (c:Chunk) RETURN DISTINCT c.source as source")
        return set(record['source'] for record in data)
    except Exception as e:
        print(f"   ⚠️ Could not fetch existing sources: {e}")
        return set()

def clear_database(graph):
    """
    DANGER: Wipes the entire database.
    """
    print("🧹 Clearing ALL data from Neo4j...")
    graph.query("MATCH (n) DETACH DELETE n")
    # We might need to drop indexes too if strictly resetting, 
    # but usually keeping indexes is fine.
    print("   ✅ Database cleared.")
