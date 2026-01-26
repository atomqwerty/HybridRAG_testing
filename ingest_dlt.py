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

from langchain_core.documents import Document
from database import create_vector_index
import hashlib
import fitz # PyMuPDF
import base64
import requests
from io import BytesIO

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
                    
                doc.close()
                logger.info(f"   ✅ Processed {len(doc)} visual chunks.")
                
            except Exception as e:
                logger.error(f"   ❌ Failed to process visual doc: {e}")


        for item in items:
            
            if "specs" in item: # It's a Car
                # Cars are mostly text/specs, keep standard graph logic
                # But if we had an image url, we could download and embed it!
                specs = item.get("specs", {})
                flat_item = item.copy()
                if "specs" in flat_item:
                    flat_item.update(flat_item.pop("specs"))
                
                props = {k: v for k, v in flat_item.items() if isinstance(v, (str, int, float, bool))}
                
                query = "MERGE (c:Car {source_url: $url}) SET c += $props"
                graph.query(query, params={"url": item.get("source_url"), "props": props})
                # Skip vectors for Cars in this MVP unless we crawl images.

            elif "type" in item and item["type"] == "pdf": # It's a Doc
                 # 1. Metadata Node 
                 query = "MERGE (d:Document {file_id: $fid}) SET d.filename = $fname"
                 graph.query(query, params={"fid": item.get("file_id"), "fname": item.get("filename")})
                 
                 # 2. VISION Processing (Pass file path)
                 # DLT item['file_id'] is the absolute path in our resource definition
                 process_doc_to_visual_chunks(item.get("file_id"), item.get("filename"))
            
            else: # Generic
                label = item.get("class", "Entity")
                identifier = item.get("id") or item.get("url") or str(uuid.uuid4())
                props = {k: v for k, v in item.items() if isinstance(v, (str, int, float, bool))}
                graph.query(f"MERGE (n:{label} {{id: $id}}) SET n += $props", params={"id": identifier, "props": props})

    except Exception as e:
        logger.error(f"Neo4j Sink Error: {e}")


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
    
    all_items = []
    for gen in data:
        all_items.extend(list(gen))
        
    load_to_neo4j(all_items)
    print("✅ Neo4j Sync Complete.")
    
    # 3. Pydantic Validation
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
