import os
import glob
import uuid
import hashlib
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

def ingest_data():
    print("🚀 Starting Advanced Hybrid RAG Data Ingestion...")
    
    # 1. Initialize Connections
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

    # Clear existing data (OPTIONAL - Be careful!)
    # print("🧹 Clearing existing database...")
    # graph.query("MATCH (n) DETACH DELETE n")

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

    # 2. Load Documents
    print("\n📂 Loading PDFs from 'data/' directory...")
    pdf_files = glob.glob("Graph-Rag-main/data/*.pdf")
    if not pdf_files:
        print("⚠️ No PDF files found in 'Graph-Rag-main/data/' folder.")
        return

    docs = []
    for pdf_file in pdf_files:
        print(f"   - Loading {pdf_file}...")
        loader = PyPDFLoader(pdf_file)
        docs.extend(loader.load())
    print(f"✅ Loaded {len(docs)} pages.")

    # 3. Chunk Text
    print("\n✂️ Splitting text into chunks...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, 
        chunk_overlap=200
    )
    
    raw_chunks = text_splitter.split_documents(docs)
    
    # Assign Attributes to Chunks (ID, Source)
    chunks_with_metadata = []
    print("   - Assigning UUIDs and computing embeddings...")
    
    chunk_data_for_cypher = []
    
    # Process only first 100 for dev speed, remove slice for production
    # LIMITING TO 100 CHUNKS FOR NOW TO SAVE TIME/COST, REMOVE [:100] FOR FULL INGEST
    processed_chunks = raw_chunks[:100] 
    
    chunk_texts = [c.page_content for c in processed_chunks]
    chunk_embeddings = embeddings.embed_documents(chunk_texts)
    
    for i, chunk in enumerate(processed_chunks):
        # Create a deterministic ID based on content to avoid duplicates
        chunk_id = hashlib.md5(chunk.page_content.encode()).hexdigest()
        source_file = chunk.metadata.get('source', 'unknown')
        page_number = chunk.metadata.get('page', 0)
        
        chunk_obj = Document(
            page_content=chunk.page_content,
            metadata={
                'id': chunk_id,
                'source': source_file,
                'page': page_number
            }
        )
        chunks_with_metadata.append(chunk_obj)
        
        chunk_data_for_cypher.append({
            'id': chunk_id,
            'text': chunk.page_content,
            'source': source_file,
            'page': page_number,
            'embedding': chunk_embeddings[i]
        })

    print(f"✅ Prepared {len(chunks_with_metadata)} chunks.")

    # 4. Ingest Chunks into Neo4j (Manually to ensure IDs and Labels)
    print("\n💾 Ingesting Chunks into Neo4j...")
    
    # Batch ingest chunks
    cypher_ingest_chunks = """
    UNWIND $batch AS data
    MERGE (c:Chunk {id: data.id})
    SET c.text = data.text,
        c.source = data.source,
        c.page = data.page,
        c.embedding = data.embedding
    """
    graph.query(cypher_ingest_chunks, {'batch': chunk_data_for_cypher})
    
    # Create Vector Index manually
    print("   - Creating Vector Index 'doc_embedding'...")
    try:
        graph.query("""
            CREATE VECTOR INDEX doc_embedding IF NOT EXISTS
            FOR (c:Chunk) ON (c.embedding)
            OPTIONS {indexConfig: {
                `vector.dimensions`: 3072,
                `vector.similarity_function`: 'cosine'
            }}
        """)
    except Exception as e:
        print(f"   (Index might already exist or error: {e})")

    # 5. Extract Graph Knowledge & Link to Chunks
    print("\n🕸️ Extracting Entities & Relationships...")
    
    llm_transformer = LLMGraphTransformer(
        llm=llm,
        allowed_nodes=["Person", "Team", "Car", "Engine", "Event", "Location", "Organization"],
        allowed_relationships=["DRIVES_FOR", "LOCATED_IN", "USES_ENGINE", "WON_RACE", "PART_OF", "MANUFACTURED_BY"]
    )
    
    # We process one by one or in small batches to maintain the link to the source chunk
    for i, chunk in enumerate(chunks_with_metadata):
        if i % 10 == 0:
            print(f"   - Processing Chunk {i+1}/{len(chunks_with_metadata)}...")
            
        graph_docs = llm_transformer.convert_to_graph_documents([chunk])
        
        if not graph_docs:
            continue
            
        # Add Custom Linking Logic
        # We need to link every node in `graph_docs` to the `chunk`
        # LangChain's add_graph_documents doesn't do this automatically for us in the way we want
        # so we will add the graph documents normally, and then run a Cypher query to link them.
        
        graph.add_graph_documents(graph_docs)
        
        # Link entities related to this chunk
        # This assumes the entities extracted are unique enough or we just link all entities 
        # found in this text. A more precise way requires inspecting graph_docs.nodes
        
        for graph_doc in graph_docs:
            for node in graph_doc.nodes:
                # Cypher to link Chunk -> Entity
                query_link = """
                MATCH (c:Chunk {id: $chunk_id})
                MERGE (e:Entity {id: $node_id})
                SET e.type = $node_type
                MERGE (c)-[:HAS_ENTITY]->(e)
                """
                graph.query(query_link, {
                    'chunk_id': chunk.metadata['id'],
                    'node_id': node.id,
                    'node_type': node.type
                })

    print("✅ Graph Extraction Complete.")

    # 6. Create Fulltext Index for Smart Search
    print("\n🔍 Creating Fulltext Index for Entities...")
    try:
        graph.query("""
            CREATE FULLTEXT INDEX entity_id_index IF NOT EXISTS 
            FOR (n:Entity) ON EACH [n.id]
        """)
    except Exception as e:
        print(f"   (Index might exist: {e})")

    print("\n🎉 Advanced Ingestion Complete!")

if __name__ == "__main__":
    ingest_data()
