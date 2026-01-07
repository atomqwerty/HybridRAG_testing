import os
import glob
import uuid
import hashlib
import time
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_core.documents import Document

# Load environment variables
load_dotenv()

# --- Configuration ---
NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

# API Keys
OPENAI_API_KEY = os.getenv('OpenAi_api')
OPENAI_EMB_KEY = os.getenv('OpenAi_api_embbeding') or OPENAI_API_KEY
OPENAI_BASE_URL = 'https://aigateway.ntictsolution.com/v1'

def clean_graph_schema(graph):
    """
    Merges duplicate entities (e.g. 'Red Bull' and 'red bull') 
    and consolidates relationships.
    """
    print("🧹 Cleaning and Consolidating Graph Schema...")
    
    # 1. Merge Duplicate Entities (Case-insensitive)
    # This matches nodes with the same ID (lowercased) and merges them
    try:
        graph.query("""
            MATCH (n:Entity)
            WITH toLower(n.id) as id, collect(n) as nodes
            WHERE size(nodes) > 1
            CALL apoc.refactor.mergeNodes(nodes, {properties: 'combine', mergeRels: true})
            YIELD node
            RETURN count(node)
        """)
        print("   ✅ Merged duplicate entities (requires APOC plugin).")
    except Exception as e:
        print(f"   ⚠️ APOC Merge failed (APOC might not be installed): {e}")

    # 2. Remove Orphan Entities (Entities with no connections)
    try:
        graph.query("""
            MATCH (n:Entity)
            WHERE NOT (n)--()
            DELETE n
        """)
        print("   ✅ Removed orphan entities.")
    except Exception as e:
        print(f"   ⚠️ Failed to remove orphans: {e}")

def enrich_communities(graph):
    """
    Runs Graph Data Science (GDS) algorithms to detect communities.
    This helps in answering broader questions by grouping related entities.
    """
    print("🏙️ Detecting Communities (GDS Louvain)...")
    
    # Check if GDS is available
    try:
        # Create In-Memory Graph projected from existing data
        graph.query("""
            CALL gds.graph.project(
                'communityGraph',
                'Entity',
                {
                    RELATED_TO: {
                        orientation: 'UNDIRECTED'
                    }
                }
            )
        """)
        
        # Run Louvain Algorithm
        graph.query("""
            CALL gds.louvain.write(
                'communityGraph',
                { writeProperty: 'communityId' }
            )
        """)
        
        # Cleanup projection
        graph.query("CALL gds.graph.drop('communityGraph')")
        
        # Index the Community IDs
        graph.query("CREATE INDEX community_id_index IF NOT EXISTS FOR (n:Entity) ON (n.communityId)")
        
        print("   ✅ Community detection complete. 'communityId' property added to Entities.")
        
    except Exception as e:
        print(f"   ⚠️ GDS Community Detection failed (GDS plugin might be missing or graph empty): {e}")

def create_indexes(graph):
    """Creates Fulltext and Vector Indexes for high-performance retrieval."""
    print("🔍 Creating Indexes...")
    
    # 1. Vector Index for Chunks
    try:
        graph.query("""
            CREATE VECTOR INDEX doc_embedding IF NOT EXISTS
            FOR (c:Chunk) ON (c.embedding)
            OPTIONS {indexConfig: {
                `vector.dimensions`: 3072,
                `vector.similarity_function`: 'cosine'
            }}
        """)
        print("   ✅ Vector Index 'doc_embedding' created.")
    except Exception as e:
        print(f"   ⚠️ Vector index error: {e}")

    # 2. Fulltext Index for Entities (Smart Search)
    try:
        graph.query("""
            CREATE FULLTEXT INDEX entity_id_index IF NOT EXISTS 
            FOR (n:Entity) ON EACH [n.id]
        """)
        print("   ✅ Fulltext Index 'entity_id_index' created.")
    except Exception as e:
        print(f"   ⚠️ Fulltext index error: {e}")

def ingest_data():
    print("🚀 Starting ULTIMATE Hybrid RAG Data Ingestion...")
    
    # --- 1. Connect ---
    try:
        graph = Neo4jGraph(
            url=NEO4J_URI,
            username=NEO4J_USERNAME,
            password=NEO4J_PASSWORD
        )
        print("✅ Connected to Neo4j")
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        return

    # Initialize Models
    llm = ChatOpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        model='gpt-4o',
        temperature=0
    )

    embeddings = OpenAIEmbeddings(
        model='text-embedding-3-large',
        openai_api_base=OPENAI_BASE_URL,
        openai_api_key=OPENAI_EMB_KEY,
        chunk_size=10
    )

    # --- 2. Load & Chunk ---
    print("\n📂 Loading & Chunking Documents...")
    pdf_files = glob.glob("data/*.pdf")
    if not pdf_files:
        print("⚠️ No PDF files found in 'Graph-Rag-main/data/'.")
        return

    docs = []
    for pdf_file in pdf_files:
        loader = PyPDFLoader(pdf_file)
        docs.extend(loader.load())
    
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=200)
    raw_chunks = text_splitter.split_documents(docs)
    
    # Re-limit for safety/cost, remove in production
    processed_chunks = raw_chunks[:100] 

    # --- 3. Prepare Attributes (UUIDs + Embeddings) ---
    print(f"   - Processing {len(processed_chunks)} chunks...")
    chunk_data_for_cypher = []
    chunks_with_metadata = []
    
    batch_emb = embeddings.embed_documents([c.page_content for c in processed_chunks])

    for i, chunk in enumerate(processed_chunks):
        chunk_id = hashlib.md5(chunk.page_content.encode()).hexdigest()
        source_file = chunk.metadata.get('source', 'unknown')
        
        chunk_doc = Document(
            page_content=chunk.page_content,
            metadata={'id': chunk_id, 'source': source_file}
        )
        chunks_with_metadata.append(chunk_doc)
        
        chunk_data_for_cypher.append({
            'id': chunk_id,
            'text': chunk.page_content,
            'source': source_file,
            'embedding': batch_emb[i]
        })

    # --- 4. Ingest Chunks (Vector Node) ---
    print("\n💾 Ingesting Chunks...")
    graph.query("""
        UNWIND $batch AS data
        MERGE (c:Chunk {id: data.id})
        SET c.text = data.text, c.source = data.source, c.embedding = data.embedding
    """, {'batch': chunk_data_for_cypher})
    
    create_indexes(graph)

    # --- 5. Extract Graph (LLM) ---
    print("\n🕸️ Extracting Graph Knowledge...")
    
    # Specific instructions to improve quality
    extraction_prompt = "Focus on Formula 1. Extract Drivers, Teams, Cars, Engines, and Races. Ignore generic car terms."
    
    llm_transformer = LLMGraphTransformer(
        llm=llm,
        allowed_nodes=["Person", "Team", "Car", "Engine", "Event", "Location", "Organization"],
        allowed_relationships=["DRIVES_FOR", "LOCATED_IN", "USES_ENGINE", "WON_RACE", "PART_OF", "MANUFACTURED_BY", "TEAMMATE_OF"],
        additional_instructions=extraction_prompt
    )

    for i, chunk in enumerate(chunks_with_metadata):
        if i % 5 == 0: print(f"   - Processing batch {i}...")
        
        # Convert single chunk
        graph_docs = llm_transformer.convert_to_graph_documents([chunk])
        
        if not graph_docs: continue
            
        graph.add_graph_documents(graph_docs)
        
        # Link Entities to Source Chunk
        for g_doc in graph_docs:
            for node in g_doc.nodes:
                graph.query("""
                    MATCH (c:Chunk {id: $chunk_id})
                    MERGE (e:Entity {id: $node_id})
                    ON CREATE SET e.type = $node_type
                    MERGE (c)-[:HAS_ENTITY]->(e)
                """, {
                    'chunk_id': chunk.metadata['id'],
                    'node_id': node.id,
                    'node_type': node.type
                })

    # --- 6. Post-Processing ---
    clean_graph_schema(graph)
    enrich_communities(graph)
    
    print("\n🎉 Ultimate Ingestion Complete!")

if __name__ == "__main__":
    ingest_data()
