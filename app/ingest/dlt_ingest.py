import dlt
from dlt.sources.helpers import requests
from typing import Iterator, Dict, Any
from app.pipeline_schemas import CarModel, TechSpecs
from app.config import Config
import json
import uuid
import os
import glob
from langchain_community.graphs import Neo4jGraph
from app.crawler import load_web_with_images, get_internal_links, init_driver
from app.logger import setup_logger

logger = setup_logger(__name__)
from app.utils import update_status, auto_add_trust_rule
from app.mineru_utils import extract_pdf_content_mineru

from langchain_core.documents import Document
from app.database import create_vector_index, create_text_vector_index, get_db_connection
import hashlib
import fitz # PyMuPDF
import base64
import requests
from io import BytesIO
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_experimental.text_splitter import SemanticChunker
from langchain_text_splitters import RecursiveCharacterTextSplitter


def apply_safety_split(chunks, limit=2000):
    """Checks for oversized semantic chunks and splits them recursively."""
    final_chunks = []
    safety_splitter = RecursiveCharacterTextSplitter(chunk_size=limit, chunk_overlap=200)
    for chunk in chunks:
        if len(chunk.page_content) > limit:
            logger.info(f"   ⚠️ Enforcing Safety Split on oversized chunk ({len(chunk.page_content)} chars)")
            sub_chunks = safety_splitter.split_documents([chunk])
            final_chunks.extend(sub_chunks)
        else:
            final_chunks.append(chunk)
    return final_chunks

# --- Graph Helpers ---
def clean_graph_schema(graph):
    """Merges duplicate entities."""
    logger.info("Cleaning and Consolidating Graph Schema...")
    try:
        graph.query("""
            MATCH (n:Entity)
            WITH toLower(n.id) as id, collect(n) as nodes
            WHERE size(nodes) > 1
            CALL apoc.refactor.mergeNodes(nodes, {properties: 'combine', mergeRels: true})
            YIELD node
            RETURN count(node)
        """)
        logger.info("Merged duplicate entities.")
    except Exception as e:
        logger.warning(f"APOC Merge failed: {e}")

    try:
        graph.query("MATCH (n:Entity) WHERE NOT (n)--() DELETE n")
        logger.info("Removed orphan entities.")
    except Exception as e:
        logger.warning(f"Failed to remove orphans: {e}")

def enrich_communities(graph):
    logger.info("Detecting Communities (GDS Louvain)...")
    try:
        graph.query("CALL gds.graph.project('communityGraph', 'Entity', '*')")
        graph.query("CALL gds.louvain.write('communityGraph', { writeProperty: 'communityId' })")
        graph.query("CALL gds.graph.drop('communityGraph') YIELD graphName")
        graph.query("CREATE INDEX community_id_index IF NOT EXISTS FOR (n:Entity) ON (n.communityId)")
        logger.info("Community detection complete.")
    except Exception as e:
        logger.warning(f"GDS Community Detection failed: {e}")

# --- Neo4j Sink ---
def load_to_neo4j(items: Iterator[Dict[str, Any]]):
    """
    custom DLT Sink to write nodes to Neo4j.
    Now includes VISION Embedding logic!
    """
    try:
        graph = Neo4jGraph(
            url=Config.NEO4J_URI,
            username=Config.NEO4J_USERNAME,
            password=Config.NEO4J_PASSWORD
        )
        
        # Ensure Vector Index Exists (Check dimension!)
        # ColPali/ColQwen usually has 128 dim (per token). 
        # If we use pooled, we need to know. For now assuming 128 based on Config.
        create_vector_index(graph, dimensions=Config.EMBEDDING_DIMENSION)
        create_text_vector_index(graph, dimensions=Config.EMBEDDING_DIMENSION)
        
        def get_visual_embedding(image_bytes):
            """Returns placeholder visual embedding."""
            # To enable real visual search, install a local VLM/CLIP model here.
            # For now, we rely on MinerU Text Search to find the image.
            return [0.0] * Config.EMBEDDING_DIMENSION

        # Initialize Text Embedding (for MinerU chunks)
        text_embeddings = OpenAIEmbeddings(
            model=Config.OPENAI_EMBEDDING_MODEL,
            api_key=Config.OPENAI_EMBEDDING_API_KEY,
            base_url=Config.OPENAI_EMBEDDING_BASE_URL
        )

        # Initialize LLM for Graph Extraction (Moved up for MinerU access)
        llm = ChatOpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_BASE_URL,
            model=Config.OPENAI_MODEL,
            temperature=0
        )
        
        # Default Schema
        allowed_nodes = ["Person", "Organization", "Event", "Location", "Product", "Service"]
        allowed_rels = ["WORKS_FOR", "LOCATED_AT", "PARTICIPATED_IN", "CREATED", "OFFERS"]
        
        llm_transformer = LLMGraphTransformer(
            llm=llm,
            allowed_nodes=allowed_nodes,
            allowed_relationships=allowed_rels
        )

        def process_doc_mineru(file_path, source_id):
            """Uses MinerU to extract high-quality text, chunk, and embed."""
            content = extract_pdf_content_mineru(file_path)
            if not content: return

            logger.info(f"   🧠 MinerU: Chunking & Embedding content for {source_id}...")
            
            # Chunking (Semantic)
            splitter = SemanticChunker(embeddings=text_embeddings)
            chunks = splitter.create_documents([content])
            chunks = apply_safety_split(chunks, limit=2000)
            
            prev_chunk_id = None
            
            for i, chunk in enumerate(chunks):
                chunk_text = chunk.page_content
                chunk_id = hashlib.md5(f"{source_id}_mineru_{i}".encode()).hexdigest()
                
                # Embed Text
                try:
                    vector = text_embeddings.embed_query(chunk_text)
                except Exception as e:
                    logger.warning(f"Embedding failed for chunk {i}: {e}")
                    vector = [0.0] * Config.EMBEDDING_DIMENSION # Fallback size, check model

                # Write to Neo4j
                query = """
                MERGE (c:Chunk {id: $id})
                SET c.text = $text,
                    c.source = $source,
                    c.seq = $seq,
                    c.text_embedding = $vector,
                    c.modality = 'mineru_text',
                    c.extraction = 'mineru',
                    c.page = 1,
                    c.image_path = $image_path
                """
                # Note: If Vector Index is shared, dimensions must match. 
                # Visual (128?) vs Text (1536/3072?). 
                # Ideally we use separate indices or projection. 
                # For now, we assume simple Hybrid (retrieval filters by modality or uses separate search).
                
                graph.query(query, {
                    "id": chunk_id,
                    "text": chunk_text,
                    "source": source_id,
                    "seq": i,
                    "vector": vector,
                    # Fallback to display the first page image for generic text hits
                    "image_path": f"{source_id}_p0.jpg" 
                })
                
                if prev_chunk_id:
                     graph.query("""
                        MATCH (c1:Chunk {id: $prev}), (c2:Chunk {id: $curr})
                        MERGE (c1)-[:NEXT]->(c2)
                    """, {"prev": prev_chunk_id, "curr": chunk_id})
                
                prev_chunk_id = chunk_id
            
            logger.info(f"   ✅ MinerU: Created {len(chunks)} text chunks.")
            
            # --- ULTIMATE HYBRID: Knowledge Graph from MinerU Text ---
            try:
                logger.info(f"   🧠 MinerU: Extracting Knowledge Graph entities...")
                # We reuse the chunks created above
                # Add metadata for graph ref
                for c in chunks: c.metadata = {"source": source_id}
                
                graph_docs = llm_transformer.convert_to_graph_documents(chunks)
                if graph_docs:
                    graph.add_graph_documents(graph_docs)
                    logger.info(f"   ✅ MinerU: Extracted {len(graph_docs[0].nodes)} entities from PDF text.")
            except Exception as e:
                logger.warning(f"MinerU Graph Extraction failed: {e}")
        def process_doc_to_visual_chunks(file_path, source_id, metadata={}):
            """Renders PDF pages as images and embeds them."""
            if not os.path.exists(file_path): return

            try:
                doc = fitz.open(file_path)
                logger.info(f"   📷 Processing {len(doc)} pages as images for {source_id}...")
                
                prev_chunk_id = None
                
                for i, page in enumerate(doc):
                    # Render page as image (medium res is fine for embedding)
                    pix = page.get_pixmap(dpi=150)
                    img_bytes = pix.tobytes("jpg")
                    
                    # SAVE IMAGE TO DISK (for UI display)
                    img_filename = f"{source_id}_p{i}.jpg"
                    save_dir = os.path.join(Config.DATA_DIR, "extracted_images")
                    os.makedirs(save_dir, exist_ok=True)
                    img_path = os.path.join(save_dir, img_filename)
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    
                    # Get Visual Vector (Semantic)
                    vector = get_visual_embedding(img_bytes)
                    
                    # Get Text Content (Keyword / Hybrid)
                    # We extract the text layer so we can still find things by exact name/keyword!
                    raw_text = page.get_text()
                    if not raw_text.strip():
                        raw_text = f"Page {i+1} of {os.path.basename(file_path)} (Image Only)"
                    
                    # Store as Chunk
                    chunk_id = hashlib.md5(f"{source_id}_p{i}".encode()).hexdigest()
                    
                    query = """
                    MERGE (c:Chunk {id: $id})
                    SET c.text = $text,
                        c.source = $source,
                        c.page = $page,
                        c.embedding = $vector,
                        c.image_path = $image_path,
                        c.seq = $seq,
                        c.last_updated = timestamp(),
                        c.modality = 'hybrid_vision'
                    """
                    params = {
                        "id": chunk_id,
                        "text": raw_text,       # <-- KEYWORD SEARCH ENABLED
                        "source": source_id,
                        "page": i+1,
                        "vector": vector,       # <-- VISION SEARCH ENABLED
                        "image_path": img_filename, # Store filename relative to DATA_DIR or extracted_images
                        "seq": i
                    }
                    graph.query(query, params)
                    
                    # NEXT relationship
                    if prev_chunk_id:
                        graph.query("""
                            MATCH (c1:Chunk {id: $prev}), (c2:Chunk {id: $curr})
                            MERGE (c1)-[:NEXT]->(c2)
                        """, {"prev": prev_chunk_id, "curr": chunk_id})
                    
                    prev_chunk_id = chunk_id
                    
                num_pages = len(doc)
                doc.close()
                logger.info(f"   ✅ Processed {num_pages} visual chunks.")
                
            except Exception as e:
                logger.error(f"   ❌ Failed to process visual doc: {e}")




        for item in items:
            if not isinstance(item, dict):
                logger.warning(f"Skipping malformed item (expected dict, got {type(item)}): {item}")
                continue
            
            if "specs" in item: # It's a Car
                # Cars are mostly text/specs, keep standard graph logic
                specs = item.get("specs", {})
                flat_item = item.copy()
                if "specs" in flat_item:
                    flat_item.update(flat_item.pop("specs"))
                
                props = {k: v for k, v in flat_item.items() if isinstance(v, (str, int, float, bool))}
                
                query = "MERGE (c:Car {source_url: $url}) SET c += $props"
                graph.query(query, params={"url": item.get("source_url"), "props": props})

            elif "type" in item and item["type"] == "pdf": # It's a Doc
                 # 1. Metadata Node 
                 query = "MERGE (d:Document {file_id: $fid}) SET d.filename = $fname"
                 graph.query(query, params={"fid": item.get("file_id"), "fname": item.get("filename")})
                 
                 # 2. VISION Processing (Pass file path)
                 process_doc_to_visual_chunks(item.get("file_id"), item.get("filename"))
                 
                 # 3. MinerU Processing (High Quality Text)
                 process_doc_mineru(item.get("file_id"), item.get("filename"))
            
            else: # Generic (Web or Text)
                label = item.get("class", "Entity")
                identifier = item.get("id") or item.get("url") or str(uuid.uuid4())
                props = {k: v for k, v in item.items() if isinstance(v, (str, int, float, bool))}
                
                # 1. Standard Vector/Chunk Node
                graph.query(f"MERGE (n:{label} {{id: $id}}) SET n += $props", params={"id": identifier, "props": props})
                
                # 2. ULTIMATE HYBRID: Chunk & Embed (For Vector Search)
                if "content" in item:
                    try:
                        logger.info(f"   🧠 Vectorizing Content for {identifier}...")
                        splitter = SemanticChunker(embeddings=text_embeddings)
                        chunks = splitter.create_documents([item['content']])
                        chunks = apply_safety_split(chunks, limit=2000)
                        
                        for i, chunk in enumerate(chunks):
                            chunk_text = chunk.page_content
                            chunk_id = hashlib.md5(f"{identifier}_web_{i}".encode()).hexdigest()
                            
                            try:
                                vector = text_embeddings.embed_query(chunk_text)
                            except:
                                vector = [0.0] * Config.EMBEDDING_DIMENSION

                            # Write Web Chunk
                            chunk_query = """
                            MERGE (c:Chunk {id: $id})
                            SET c.text = $text,
                                c.source = $source,
                                c.seq = $seq,
                                c.text_embedding = $vector,
                                c.modality = 'web_text',
                                c.page = 1,
                                c.image_path = $image_path 
                            """
                            # Use a default image if available (from metadata?) or placeholder
                            img_path = item.get("metadata", {}).get("image_path", "default.jpg") 
                            
                            graph.query(chunk_query, {
                                "id": chunk_id,
                                "text": chunk_text,
                                "source": identifier,
                                "seq": i,
                                "vector": vector,
                                "image_path": img_path
                            })

                        logger.info(f"   ✅ Created {len(chunks)} vector chunks for {identifier}.")

                    except Exception as e:
                        logger.warning(f"Vectorization failed for {identifier}: {e}")

                    # 3. Knowledge Graph Extraction
                    try:
                        logger.info(f"   🧠 Extracting Knowledge Graph for {identifier}...")
                        doc = Document(page_content=item['content'], metadata={"source": identifier})
                        graph_docs = llm_transformer.convert_to_graph_documents([doc])
                        if graph_docs:
                            graph.add_graph_documents(graph_docs)
                            logger.info(f"   ✅ Extracted KG: {len(graph_docs[0].nodes)} nodes.")
                    except Exception as e:
                        logger.warning(f"Graph extraction failed for {identifier}: {e}")


    except Exception as e:
        logger.error(f"Neo4j Sink Error: {e}")

@dlt.resource(name="hybrid_rag_data", write_disposition="replace")
def hybrid_rag_source(urls: list, files: list, existing_ids: set = None):
    """
    DLT Resource that yields data from both Files and URLs.
    """
    # 1. Yield Files (Metadata only, heavy processing in Sink)
    for file_path in files:
        yield {
            "type": "pdf" if file_path.lower().endswith(".pdf") else "file",
            "file_id": file_path,
            "filename": os.path.basename(file_path),
            "source_type": "filesystem"
        }
        
    # 2. Yield URLs (Scraped Content)
    for url in urls:
        try:
            print(f"DEBUG: Starting processing for URL: {url}")
            # Check if it's a placeholder
            if "example.com" in url: 
                print(f"DEBUG: Skipping placeholder {url}")
                continue
            
            print(f"DEBUG: deep crawling for {url}...")
            # 1. Discover Sub-pages (Crawl)
            sub_urls = get_internal_links(url, max_links=300) # Increased to 300 for better breadth
            all_urls = [url] + sub_urls
            # Remove duplicates
            all_urls = list(set(all_urls))
            
            print(f"DEBUG: Found {len(all_urls)} pages to scrape for {url}")
            
            # Incremental Check per Page
            if existing_ids:
                new_urls = [u for u in all_urls if u not in existing_ids]
                if not new_urls:
                    print(f"DEBUG: All {len(all_urls)} pages already ingested for {url}. Skipping.")
                    continue
                print(f"DEBUG: found {len(new_urls)} NEW pages to ingest (from {len(all_urls)} candidates).")
                all_urls = new_urls

            # --- OPTIMIZATION: Use Shared Driver ---
            driver = None
            try:
                driver = init_driver()
            except Exception as e:
                print(f"DEBUG: Failed to init shared driver: {e}")
            
            try:
                for page_url in all_urls:
                    try:
                        print(f"DEBUG: Calling load_web_with_images for {page_url}")
                        # Pass shared driver!
                        docs = load_web_with_images(page_url, driver=driver)
                        print(f"DEBUG: Received {len(docs)} docs from {page_url}")
                        
                        for doc in docs:
                            yield {
                                "type": "web",
                                "url": page_url,
                                "content": doc.page_content,
                                "metadata": doc.metadata,
                                "source_type": "web"
                            }
                    except Exception as e:
                         print(f"DEBUG: Error processing page {page_url}: {e}")
                         continue
            finally:
                if driver:
                    print("DEBUG: Quitting Shared Driver...")
                    driver.quit()
            # ---------------------------------------
        except Exception as e:
            print(f"DEBUG: Error processing {url}: {e}")
            logger.error(f"Failed to yield URL {url}: {e}")



from app.ingest.base import BaseIngestor

class DLTIngestor(BaseIngestor):
    """DLT-based Ingestion Strategy."""
    
    def ingest_document(self, file_path: str, source_type: str = "file") -> Dict[str, Any]:
        """Ingests a single document using DLT Pipeline."""
        logger.info(f"🚀 Starting DLT Ingestion for {file_path}...")
        update_status(f"Starting ingestion for {os.path.basename(file_path)}...", 10)
        
        try:
            # 1. Setup Pipeline
            output_dir = os.path.join(Config.DATA_DIR, "dlt_output")
            os.makedirs(output_dir, exist_ok=True)
            
            pipeline = dlt.pipeline(
                pipeline_name="hybrid_ingestion",
                destination=dlt.destinations.filesystem(bucket_url=f"file://{output_dir}"), 
                dataset_name="hybrid_data"
            )
            
            # 2. Run Pipeline (Single File)
            # We pass empty set() for existing_ids to force ingestion
            target_files = [file_path]
            target_urls = []
            
            load_info = pipeline.run(
                hybrid_rag_source(target_urls, target_files, set()), 
                loader_file_format="jsonl"
            )
            logger.info(f"DLT Load Info: {load_info}")
            update_status("Extracting PDF content (MinerU / Vision)...", 30)
            
            # 3. Sync to Neo4j
            all_items = list(hybrid_rag_source(target_urls, target_files, set()))
            load_to_neo4j(all_items)
            update_status("Building Knowledge Graph and Vector Chunks...", 70)
            
            # 4. Enrich
            graph = Neo4jGraph(url=Config.NEO4J_URI, username=Config.NEO4J_USERNAME, password=Config.NEO4J_PASSWORD)
            clean_graph_schema(graph)
            enrich_communities(graph)
            
            # 5. Metadata/Trust
            filename = os.path.basename(file_path)
            auto_add_trust_rule(filename, score=1.0, rule_type='file')
            update_status("Ingestion Complete. Refreshing UI.", 100)
            
            logger.info(f"✅ Successfully ingested {filename}")
            return {"status": "success", "message": f"Ingested {filename}"}
            
        except Exception as e:
            logger.error(f"DLT Ingestion Failed: {e}")
            update_status(f"Ingestion failed: {e}", 0, "failed")
            raise e

    def ingest_url(self, url: str) -> Dict[str, Any]:
        """Ingests a URL recursively using the existing deep crawler logic."""
        logger.info(f"🚀 Starting DLT Ingestion for URL {url}...")
        update_status(f"Crawling URL {url}...", 10)
        
        try:
            output_dir = os.path.join(Config.DATA_DIR, "dlt_output")
            os.makedirs(output_dir, exist_ok=True)
            
            pipeline = dlt.pipeline(
                pipeline_name="hybrid_ingestion",
                destination=dlt.destinations.filesystem(bucket_url=f"file://{output_dir}"), 
                dataset_name="hybrid_data"
            )
            
            target_urls = [url]
            target_files = []
            
            # The resource handles crawling logic internally
            load_info = pipeline.run(
                hybrid_rag_source(target_urls, target_files, set()), 
                loader_file_format="jsonl"
            )
            logger.info(f"DLT URL Load Info: {load_info}")
            update_status("Rendering Webpages and embedding text...", 40)
            
            # Sync to Neo4j
            all_items = list(hybrid_rag_source(target_urls, target_files, set()))
            load_to_neo4j(all_items)
            update_status("Extracting entities into Knowledge Graph...", 75)
            
            # Enrich
            graph = Neo4jGraph(url=Config.NEO4J_URI, username=Config.NEO4J_USERNAME, password=Config.NEO4J_PASSWORD)
            clean_graph_schema(graph)
            enrich_communities(graph)
            
            # Trust
            from urllib.parse import urlparse
            try:
                domain = urlparse(url).netloc.replace('www.', '')
                if domain: 
                    auto_add_trust_rule(domain, score=1.0, rule_type='domain')
            except: pass
            
            update_status("Web Crawl Complete. Refreshing UI.", 100)
            logger.info(f"✅ Successfully crawled {url}")
            return {"status": "success", "message": f"Crawled & Ingested {url}"}
            
        except Exception as e:
            logger.error(f"DLT URL Ingestion Failed: {e}")
            update_status(f"URL Crawl failed: {e}", 0, "failed")
            raise e
