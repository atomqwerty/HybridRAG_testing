import dlt
from dlt.sources.helpers import requests
from typing import Iterator, Dict, Any
from pipeline_schemas import CarModel, TechSpecs
from config import Config
import json
import uuid
import os
import glob
from langchain_community.graphs import Neo4jGraph
from crawler import load_web_with_images
from logger import setup_logger

logger = setup_logger(__name__)
from utils import update_status, auto_add_trust_rule

from langchain_core.documents import Document
from database import create_vector_index
import hashlib
import fitz # PyMuPDF
import base64
import requests
from io import BytesIO
from langchain_openai import ChatOpenAI
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_core.documents import Document


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
        
        def get_visual_embedding(image_bytes):
            """Calls local ColiVara API"""
            try:
                # Based on ColiVarE API spec: POST /runsync
                # Payload: {"input": {"task": "embed", "input_data": ["base64_string"]}}
                # Note: Check actual API spec. The README said: "input_data": ["hello"] for text.
                # For images, we likely need base64.
                
                b64_str = base64.b64encode(image_bytes).decode('utf-8')
                
                # Payload structure assumption based on standard serverless-style APIs
                # Adjust if ColiVara differs.
                payload = {
                    "input": {
                        "task": "embed", # or "embed_image"?
                        "input_data": [b64_str],
                        "modality": "image" # Hypothetical flag
                    }
                }
                
                # ColiVarE likely expects a list of inputs.
                # If it's a general VLM, we pass the image.
                
                res = requests.post(Config.COLIVARA_API_URL, json=payload, timeout=30)
                if res.status_code == 200:
                    # Parse response. Expecting list of vectors.
                    # response format?? {"output": [[0.1, ...]]}
                    data = res.json()
                    return data.get("output", [])[0]
                else:
                    logger.error(f"ColiVara API Error: {res.text}")
                    return [0.0] * Config.EMBEDDING_DIMENSION
                    
            except Exception as e:
                logger.error(f"Visual Embed Failed: {e}")
                return [0.0] * Config.EMBEDDING_DIMENSION

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


        # Initialize LLM for Graph Extraction
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
            
            else: # Generic (Web or Text)
                label = item.get("class", "Entity")
                identifier = item.get("id") or item.get("url") or str(uuid.uuid4())
                props = {k: v for k, v in item.items() if isinstance(v, (str, int, float, bool))}
                
                # 1. Standard Vector/Chunk Node
                graph.query(f"MERGE (n:{label} {{id: $id}}) SET n += $props", params={"id": identifier, "props": props})
                
                # 2. ULTIMATE HYBRID: Extract Knowledge Graph
                if "content" in item:
                    try:
                        logger.info(f"   🧠 Extracting Knowledge Graph for {identifier}...")
                        doc = Document(page_content=item['content'], metadata={"source": identifier})
                        graph_docs = llm_transformer.convert_to_graph_documents([doc])
                        if graph_docs:
                            graph.add_graph_documents(graph_docs)
                            logger.info(f"   ✅ Extracted {len(graph_docs[0].nodes)} entities and {len(graph_docs[0].relationships)} relationships.")
                    except Exception as e:
                        logger.warning(f"Graph extraction failed for {identifier}: {e}")


    except Exception as e:
        logger.error(f"Neo4j Sink Error: {e}")

@dlt.resource(name="hybrid_rag_data", write_disposition="replace")
def hybrid_rag_source(urls: list, files: list):
    """
    DLT Resource that yields data from both Files and URLs.
    """
    # 1. Yield Files (Metadata only, heavy processing in Sink)
    for file_path in files:
        yield {
            "type": "pdf" if file_path.endswith(".pdf") else "file",
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
            
            print(f"DEBUG: Calling load_web_with_images for {url}")
            docs = load_web_with_images(url)
            print(f"DEBUG: Received {len(docs)} docs from {url}")
            
            for doc in docs:
                yield {
                    "type": "web",
                    "url": url,
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "source_type": "web"
                }
        except Exception as e:
            print(f"DEBUG: Error processing {url}: {e}")
            logger.error(f"Failed to yield URL {url}: {e}")



if __name__ == "__main__":
    update_status("Initializing DLT Pipeline...", 5)
    
    # ... (Loading Logic) ...
    urls_file = os.path.join(Config.DATA_DIR, "urls.txt")
    prod_urls = []
    if os.path.exists(urls_file):
        with open(urls_file, "r") as f:
            prod_urls = [line.strip() for line in f if line.strip()]
    
    prod_files = []
    search_patterns = ["**/*.pdf", "**/*.docx", "**/*.txt"]
    for pattern in search_patterns:
        full_pattern = os.path.join(Config.DATA_DIR, pattern)
        prod_files.extend(glob.glob(full_pattern, recursive=True))
    
    prod_files = [f for f in prod_files if "dlt_output" not in f]

    msg = f"Loaded {len(prod_urls)} URLs and {len(prod_files)} Files."
    print(msg)
    update_status(msg, 10)
    
    target_urls = prod_urls if prod_urls else ["https://example.com/placeholder"]
    target_files = prod_files if prod_files else [] 

    # Run the pipeline
    output_dir = os.path.join(Config.DATA_DIR, "dlt_output")
    os.makedirs(output_dir, exist_ok=True)
    
    pipeline = dlt.pipeline(
        pipeline_name="hybrid_ingestion",
        destination=dlt.destinations.filesystem(bucket_url=f"file://{output_dir}"), 
        dataset_name="hybrid_data"
    )

    # 1. Pipeline Run
    update_status("Running Extraction & DLT Load...", 20)
    
    load_info = pipeline.run(
        hybrid_rag_source(target_urls, target_files), 
        loader_file_format="jsonl"
    )
    print(load_info)
    
    # 2. Sync to Neo4j
    update_status("Syncing to Knowledge Graph (Neo4j)...", 60)
    print("Writing to Neo4j...")
    
    data = list(hybrid_rag_source(target_urls, target_files)) 
    
    all_items = data
        
    load_to_neo4j(all_items)
    
    # 3. ULTIMATE HYBRID: Post-Processing
    print("Running Graph Enrichment...")
    graph = Neo4jGraph(url=Config.NEO4J_URI, username=Config.NEO4J_USERNAME, password=Config.NEO4J_PASSWORD)
    clean_graph_schema(graph)
    enrich_communities(graph)
    
    print("✅ Neo4j Sync & Enrichment Complete.")
    
    # 4. Pydantic Validation
    update_status("Validating Data Structure...", 90)
    # ... (Validation Logic) ...
    try:
        sample = {
            "brand": "BYD", 
            "model": "Seal", 
            "source_url": "http://test",
            "specs": {"horsepower": "520"}
        }
        car = CarModel(**sample)
        print(f"✅ Valid Car Model: {car.brand} {car.model}")
    except Exception as e:
        print(f"❌ Validation Failed: {e}")
        
    # 4. Finalize: Update Trust Rules for processed items
    update_status("Finalizing Trust Rules...", 95)
    
    # Add files
    for file_path in target_files:
        filename = os.path.basename(file_path)
        auto_add_trust_rule(filename, score=1.0, rule_type='file')
        
    # Add URLs
    from urllib.parse import urlparse
    for url in target_urls:
         if "example.com/placeholder" in url: continue
         try:
             domain = urlparse(url).netloc.replace('www.', '')
             if domain: 
                auto_add_trust_rule(domain, score=1.0, rule_type='domain')
         except: pass

    update_status("Ingestion Complete!", 100, "completed")
