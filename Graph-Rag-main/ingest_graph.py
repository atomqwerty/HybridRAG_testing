import os
import glob
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_community.vectorstores import Neo4jVector

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
    print("🚀 Starting Hybrid RAG Data Ingestion...")
    
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
        chunk_size=10  # Reduced batch size to avoid 413 Errors
    )

    # 2. Load Documents
    print("\n📂 Loading PDFs from 'data/' directory...")
    pdf_files = glob.glob("Graph-Rag-main\data\*.pdf")
    if not pdf_files:
        print("⚠️ No PDF files found in 'data/' folder.")
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
    chunks = text_splitter.split_documents(docs)
    print(f"✅ Created {len(chunks)} chunks.")

    # 4. Create Vector Index (Chunks -> Vector Store)
    # This stores the processing text chunks into Neo4j with vector embeddings
    print("\n🧠 Creating/Updating Vector Index 'doc_embedding'...")
    try:
        # We process in batches manually for Neo4jVector if needed, but 'embeddings.chunk_size' should handle API calls.
        # However, sending too huge a list to from_documents might also hit limits if it constructs a huge cypher query.
        # Let's rely on the embeddings chunk_size first.
        Neo4jVector.from_documents(
            chunks,
            embeddings,
            url=NEO4J_URI,
            username=NEO4J_USERNAME,
            password=NEO4J_PASSWORD,
            index_name="doc_embedding",  # Must match the query code
            node_label="Document",       # Label for the text chunks
            text_node_property="text",
            embedding_node_property="embedding"
        )
        print("✅ Vector Index populated.")
    except Exception as e:
        print(f"❌ Error creating vector index: {e}")

    # 5. Extract Graph Knowledge (Text -> Entities/Relations)
    # This uses the LLM to understand the text and build the graph structure
    print("\n🕸️ Extracting Entities & Relationships (Graph Transformer)...")
    print("   (This uses GPT-4o. LIMITING to first 50 chunks for demo purposes.)")
    print("   (Edit the script to remove the [:50] slice to process all data.)")
    
    llm_transformer = LLMGraphTransformer(llm=llm)
    
    # LIMIT to first 50 chunks to avoid massive cost/time during dev
    subset_chunks = chunks[:50]
    
    graph_documents = llm_transformer.convert_to_graph_documents(subset_chunks)
    
    print(f"✅ Extracted {len(graph_documents)} graph documents.")
    
    print("   - Writing to Neo4j...")
    graph.add_graph_documents(graph_documents)
    print("✅ Knowledge Graph successfully populated!")

    print("\n🎉 Ingestion Complete. You can now run the query notebooks.")

if __name__ == "__main__":
    ingest_data()
