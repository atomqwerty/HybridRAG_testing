import os
import glob
import time
import hashlib
import uuid
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.document_loaders import PyPDFLoader, PDFPlumberLoader, Docx2txtLoader, TextLoader, UnstructuredImageLoader, WebBaseLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_experimental.text_splitter import SemanticChunker
from langchain_core.documents import Document
import pdfplumber
from vision_utils import describe_image, encode_image_from_bytes, encode_image_from_file

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
                '*'
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

def get_combined_chunks(docs, chunks_to_combine=3):
    """
    Combines multiple chunks into a single document to provide more context 
    to the LLM during extraction.
    """
    combined = []
    print(f"   - Combining chunks (Group Size: {chunks_to_combine})...")
    
    for i in range(0, len(docs), chunks_to_combine):
        batch = docs[i : i + chunks_to_combine]
        
        # Join content with newlines
        combined_content = "\n\n".join([d.page_content for d in batch])
        combined_ids = [d.metadata['id'] for d in batch]
        
        new_doc = Document(
            page_content=combined_content,
            metadata={"combined_chunk_ids": combined_ids}
        )
        combined.append(new_doc)
    
    return combined

def load_web_with_images(url):
    """
    Scrapes a webpage, downloads meaningful images, and generates a document 
    combining text and automated image descriptions.
    """
    from bs4 import BeautifulSoup
    import requests
    from urllib.parse import urljoin
    
    print(f"   - Scraping (Multimodal): {url}")
    
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 1. Extract Images
        images = soup.find_all('img')
        image_descriptions = ""
        
        for i, img in enumerate(images):
            src = img.get('src')
            if not src: continue
            
            # Resolve relative URLs
            full_url = urljoin(url, src)
            
            try:
                # Download image
                img_resp = requests.get(full_url, stream=True)
                if img_resp.status_code != 200: continue
                
                # Check size (Skip small icons < 5KB)
                if len(img_resp.content) < 5000: continue
                
                # Save locally
                img_filename = f"web_{uuid.uuid4().hex[:8]}.jpg"
                save_dir = Path("data/extracted_images")
                save_dir.mkdir(parents=True, exist_ok=True)
                img_path = save_dir / img_filename
                
                with open(img_path, "wb") as f:
                    f.write(img_resp.content)
                
                # Analyze with Vision
                print(f"      📸 Analyzed Web Image: {os.path.basename(full_url)}")
                b64 = encode_image_from_file(str(img_path))
                
                # Save description
                log_dir = Path("log")
                log_dir.mkdir(parents=True, exist_ok=True)
                desc_path = log_dir / (img_filename + '_description.txt')
                desc = describe_image(b64, save_description_path=str(desc_path))
                
                image_descriptions += f"\n[IMAGE PATH: {img_path}]\n[SOURCE URL: {full_url}]\n{desc}\n"
                
            except Exception as e:
                # print(f"      ⚠️ Failed to process image {src}: {e}")
                continue
                
        # 2. Extract Text
        # Remove scripts and styles
        for script in soup(["script", "style"]):
            script.decompose()
            
        text = soup.get_text(separator='\n')
        
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\n'.join(line for line in lines if line)
        
        # Combine
        full_content = f"Source URL: {url}\n\n{clean_text}\n\n### DETECTED IMAGES FROM WEBPAGE:\n{image_descriptions}"
        
        return [Document(
            page_content=full_content,
            metadata={"source": url, "title": soup.title.string if soup.title else url}
        )]
        
    except Exception as e:
        print(f"      ❌ Web Scraping failed for {url}: {e}")
        return []

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
        
        # Clear existing data for a fresh start with PDFPlumber
        print("🧹 Clearing existing database to ensure clean table ingestion...")
        graph.query("MATCH (n) DETACH DELETE n")
        print("   ✅ Database cleared.")
        
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
    print("\n📂 Loading & Chunking Documents (PDF, DOCX, TXT)...")
    
    # Get all files in data directory
    all_files = glob.glob("data/*")
    
    docs = []
    
    for file_path in all_files:
        ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if ext == '.pdf':
                print(f"   - Loading PDF (Multimodal): {os.path.basename(file_path)}")
                
                with pdfplumber.open(file_path) as pdf:
                    for i, page in enumerate(pdf.pages):
                        # 1. Extract Text
                        text = page.extract_text() or ""
                        
                        # 2. Extract Tables (The "Secret Weapon")
                        tables = page.extract_tables()
                        table_text = ""
                        if tables:
                            print(f"      📊 Found {len(tables)} table(s) on page {i+1}")
                            for table in tables:
                                # Convert table to Markdown format
                                # Filter out None values and empty rows
                                clean_table = [[cell or "" for cell in row] for row in table if any(row)]
                                if clean_table:
                                    # Create header and rows
                                    try:
                                        # Simple markdown conversion
                                        header = "| " + " | ".join(clean_table[0]) + " |"
                                        separator = "| " + " | ".join(["---"] * len(clean_table[0])) + " |"
                                        body = "\n".join(["| " + " | ".join(row) + " |" for row in clean_table[1:]])
                                        table_markdown = f"\n\n### TABLE DATA (Page {i+1}):\n{header}\n{separator}\n{body}\n"
                                        table_text += table_markdown
                                    except Exception as e:
                                        print(f"      ⚠️ Could not format table: {e}")

                        # Combine Text + Table Data
                        final_content = text + "\n" + table_text
                        
                        # 3. Extract Images (Existing Logic)
                        image_descriptions = ""
                        for img in page.images:
                            # Filter small icons (e.g. logos)
                            if img['width'] < 100 or img['height'] < 100: continue
                            
                            try:
                                # Get image bytes
                                img_obj = page.crop( (img['x0'], img['top'], img['x1'], img['bottom']) ).to_image()
                                if img_obj.original.mode not in ('RGB', 'L'):
                                    img_obj.original = img_obj.original.convert('RGB')
                                
                                # Convert to bytes compatible with our util
                                import io
                                buf = io.BytesIO()
                                img_obj.original.save(buf, format="JPEG")
                                img_bytes = buf.getvalue()
                                
                                # --- SAVE LOCALLY ---
                                img_filename = f"img_{uuid.uuid4().hex[:8]}.jpg"
                                img_path = Path("data/extracted_images") / img_filename
                                img_path.parent.mkdir(parents=True, exist_ok=True)
                                img_obj.original.save(img_path, format="JPEG")
                                
                                # Describe
                                print(f"      Possible Chart/Image on P{i+1}. Analyzing with Vision...")
                                b64 = encode_image_from_bytes(img_bytes)
                                
                                # Save description to log directory
                                log_dir = Path("log")
                                if not log_dir.exists():
                                    log_dir.mkdir(parents=True, exist_ok=True)
                                desc_filename = img_path.stem + '_description.txt'
                                desc_path = log_dir / desc_filename
                                desc = describe_image(b64, save_description_path=str(desc_path))
                                image_descriptions += f"\n[IMAGE PATH: {img_path}]\n{desc}"
                            except Exception as e_img:
                                print(f"      ⚠️ Image processing failed: {e_img}")

                        # 3. Create Document
                        full_content = text + "\n" + image_descriptions
                        doc = Document(
                            page_content=full_content,
                            metadata={"source": os.path.basename(file_path), "page": i+1}
                        )
                        docs.append(doc)
                
            elif ext == '.docx':
                print(f"   - Loading DOCX (Multimodal): {os.path.basename(file_path)}")
                try:
                    import docx2txt
                    # Temporary directory for extracting images from this specific doc
                    img_extract_dir = "data/extracted_images"
                    os.makedirs(img_extract_dir, exist_ok=True)
                    
                    # Extract text and save images
                    text = docx2txt.process(file_path, img_extract_dir)
                    
                    # Now find the images that were just extracted
                    # docx2txt naming convention isn't easily predictable for mapping exact position,
                    # so we append all new images found to the end of the text.
                    # A more robust way requires unzip manipulation, but this works for RAG context.
                    
                    # We can iterate over all images in that dir checking creation time? 
                    # Simpler: docx2txt saves them as 'image1.png', 'image2.jpg', etc. 
                    # We might clash if we don't manage names. 
                    # BETTER STRATEGY: Rename them immediately or use a unique temp dir per file.
                    
                    # RE-DO: Use a unique sub-folder for this file
                    unique_id = uuid.uuid4().hex[:8]
                    temp_img_dir = Path(f"data/extracted_images/docx_{unique_id}")
                    temp_img_dir.mkdir(parents=True, exist_ok=True)
                    
                    text = docx2txt.process(file_path, str(temp_img_dir))
                    
                    # Iterate over extracted images
                    image_descriptions = ""
                    if temp_img_dir.exists():
                        for img_file in temp_img_dir.iterdir():
                            if img_file.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                                print(f"      🖼️ Found DOCX Image: {img_file.name}")
                                
                                b64 = encode_image_from_file(str(img_file))
                                
                                log_dir = Path("log")
                                log_dir.mkdir(parents=True, exist_ok=True)
                                desc_path = log_dir / (img_file.name + '_description.txt')
                                
                                desc = describe_image(b64, save_description_path=str(desc_path))
                                image_descriptions += f"\n[IMAGE PATH: {img_file}]\n{desc}\n"
                    
                    full_content = text + "\n\n### EXTRACTED IMAGES FROM DOCX:\n" + image_descriptions
                    
                    docs.append(Document(
                        page_content=full_content,
                        metadata={"source": os.path.basename(file_path)}
                    ))
                    
                except ImportError:
                     print("      ❌ Missing 'docx2txt'. Install it: `pip install docx2txt`")
                     
            elif ext == '.txt':
                 # Skip the config file for URLs, processed later
                 if os.path.basename(file_path) == "urls.txt":
                     continue
                     
                 print(f"   - Loading TXT: {os.path.basename(file_path)}")
                 loader = TextLoader(file_path)
                 docs.extend(loader.load())

            elif ext in ['.png', '.jpg', '.jpeg']:
                 print(f"   - Loading Image: {os.path.basename(file_path)}")
                 b64 = encode_image_from_file(file_path)
                 
                 # Save description to log directory
                 desc_filename = Path(file_path).stem + '_description.txt'
                 log_dir = Path("log")
                 if not log_dir.exists():
                     log_dir.mkdir(parents=True, exist_ok=True)
                 desc_path = log_dir / desc_filename
                 desc = describe_image(b64, save_description_path=str(desc_path))
                 
                 # Store the image path relative to project root
                 abs_file_path = Path(file_path).resolve()
                 try:
                     img_path = abs_file_path.relative_to(Path.cwd())
                 except ValueError:
                     # If relative_to fails, just use the file path as-is
                     img_path = Path(file_path)
                 
                 doc = Document(
                     page_content=f"[IMAGE PATH: {img_path}]\n[IMAGE FILE SOURCE: {os.path.basename(file_path)}]\n{desc}",
                     metadata={"source": os.path.basename(file_path)}
                 )
                 docs.append(doc)
                 
            else:
                pass # Skip unknown
                
        except Exception as e:
            print(f"   ⚠️ Failed to load {file_path}: {e}")
            
    if not docs and not os.path.exists("data/urls.txt"):
        print("❌ No documents or URLs found. Exiting.")
        return

    # --- 2b. Load from Web (if urls.txt exists) ---
    url_file = "data/urls.txt"
    if os.path.exists(url_file):
        print(f"\n🌐 Found {url_file}, loading websites...")
        with open(url_file, "r") as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        
        if urls:
            print(f"   - Processing {len(urls)} URLs...")
            for url in urls:
                try:
                    web_docs = load_web_with_images(url)
                    docs.extend(web_docs)
                except Exception as e:
                     print(f"      ⚠️ Failed to load {url}: {e}")
        else:
            print("   (urls.txt is empty)")
            
    if not docs:
        print("❌ No content loaded (files or web). Exiting.")
        return
    
    # --- Smart Chunking Logic ---
    print("   (Applying Smart Hybrid Chunking: Tables -> Page-Based, Text -> Semantic Split)")
    
    def is_table_page(text):
        """
        Detects if a page looks like a table based on structural layout 
        (multiple columns separated by whitespace).
        """
        lines = text.split('\n')
        table_like_lines = 0
        for line in lines:
            # Check for at least 3 columns separated by 3+ spaces
            columns = [c for c in line.split('   ') if c.strip()]
            if len(columns) >= 3:
                table_like_lines += 1
        
        # If >5 lines align like a table, treat page as a table
        return table_like_lines >= 5

    final_chunks = []
    # Initialize Semantic Chunker for better narrative splitting
    # "percentile" threshold works well for general text
    semantic_splitter = SemanticChunker(embeddings, breakpoint_threshold_type="percentile")

    for i, doc in enumerate(docs):
        print(f"      - Chunking document {i+1}/{len(docs)}...", end='\r') # Dynamic progress line
        
        # Check if this is an image document (contains [IMAGE PATH:])
        if '[IMAGE PATH:' in doc.page_content or '[IMAGE FILE SOURCE:' in doc.page_content:
            print(f"      - Image document detected. Keeping intact: {doc.metadata.get('source', 'Unknown')}")
            final_chunks.append(doc)
        elif is_table_page(doc.page_content):
            print(f"      - Page {doc.metadata.get('page', '?')}: Table detected. Keeping intact.")
            final_chunks.append(doc)
        else:
            # Normal text page -> Semantic Split
            try:
                splits = semantic_splitter.split_documents([doc])
                final_chunks.extend(splits)
            except Exception as e:
                print(f"      ⚠️ Semantic chunking failed on page {doc.metadata.get('page', '?')}, falling back to whole page: {e}")
                final_chunks.append(doc)
            
    raw_chunks = final_chunks
    
    # Process ALL chunks for Production
    processed_chunks = raw_chunks
    # processed_chunks = raw_chunks[:100] # Uncomment for testing 

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
            'page': chunk.metadata.get('page', None),
            'embedding': batch_emb[i]
        })

    # --- 4. Ingest Chunks (Vector Node) ---
    print("\n💾 Ingesting Chunks...")
    graph.query("""
        UNWIND $batch AS data
        MERGE (c:Chunk {id: data.id})
        SET c.text = data.text, c.source = data.source, c.page = data.page, c.embedding = data.embedding
    """, {'batch': chunk_data_for_cypher})
    
    create_indexes(graph)

    # --- 5. Extract Graph (LLM) ---
    print("\n🕸️ Extracting Graph Knowledge (with Chunk Combination)...")
    
    # Combine chunks (increase to 4 for speed/efficiency with GPT-4o)
    combined_docs = get_combined_chunks(chunks_with_metadata, chunks_to_combine=4)
    
     # Configuration for Extraction
    # Can be set in .env. If "OPEN", extraction is unrestricted.
    env_nodes = os.getenv('ALLOWED_NODES')
    env_rels = os.getenv('ALLOWED_RELATIONSHIPS')
    
    if env_nodes == "OPEN":
        allowed_nodes = [] # Unrestricted
        print("   - Strategy: Open Extraction (No Node Constraints)")
    elif env_nodes:
        allowed_nodes = [n.strip() for n in env_nodes.split(',') if n.strip()]
        print(f"   - Strategy: Custom Nodes from Env: {allowed_nodes}")
    else:
        # Default to F1 SCHEMA (Better structured data)
        allowed_nodes = ["Driver", "Team", "Person", "Car", "Part", "Race", "Circuit", "Location", "Year", "Event", "Organization"]
        print(f"   - Strategy: Default F1 Schema Nodes: {allowed_nodes}")

    if env_rels == "OPEN":
        allowed_rels = [] # Unrestricted
        print("   - Strategy: Open Extraction (No Relationship Constraints)")
    elif env_rels:
        allowed_rels = [r.strip() for r in env_rels.split(',') if r.strip()]
        # Simple validation could go here later if needed
        print(f"   - Strategy: Custom Relationships from Env: {allowed_rels}")
    else:
        # Default to F1 SCHEMA
        allowed_rels = ["DRIVES_FOR", "WORKS_FOR", "LOCATED_AT", "PARTICIPATED_IN", "WON", "HAS_PART", "OCCURRED_IN", "ALSO_KNOWN_AS", "HAS_BUDGET", "EARNED"]
        print(f"   - Strategy: Default F1 Schema Relationships: {allowed_rels}")

    llm_transformer = LLMGraphTransformer(
        llm=llm,
        allowed_nodes=allowed_nodes,
        allowed_relationships=allowed_rels
    )
    
    # Process in Smaller Batches
    BATCH_SIZE = 5
    total_batches = (len(combined_docs) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        end = start + BATCH_SIZE
        batch_combined = combined_docs[start:end]
        
        print(f"   - Processing Batch {batch_idx + 1}/{total_batches} ({len(batch_combined)} combined docs)...")
        
        try:
            print("      > Sending request to LLM (this may take 10-20s)...")
            graph_docs = llm_transformer.convert_to_graph_documents(batch_combined)
            print("      > Received response from LLM.")
            
            if not graph_docs: continue
            
            graph.add_graph_documents(graph_docs)
            
            # Link Entities to ALL Source Chunks
            for g_doc in graph_docs:
                # Get the list of chunk IDs this graph doc was derived from
                chunk_ids = g_doc.source.metadata.get('combined_chunk_ids', [])
                
                for chunk_id in chunk_ids:
                    for node in g_doc.nodes:
                        graph.query("""
                            MATCH (c:Chunk {id: $chunk_id})
                            MERGE (e:Entity {id: $node_id})
                            ON CREATE SET e.type = $node_type
                            MERGE (c)-[:HAS_ENTITY]->(e)
                        """, {
                            'chunk_id': chunk_id,
                            'node_id': node.id,
                            'node_type': node.type
                        })
                    
        except Exception as e:
            print(f"   ⚠️ Error processing batch {batch_idx + 1}: {e}")

    # --- 6. Post-Processing ---
    clean_graph_schema(graph)
    enrich_communities(graph)
    
    print("\n🎉 Ultimate Ingestion Complete!")

if __name__ == "__main__":
    ingest_data()

#start Data Ingestion 8:49
#Extracting Graph Knowledge 3:58
#Ending Ingestion 9:
