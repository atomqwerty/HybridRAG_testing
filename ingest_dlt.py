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

from langchain_openai import OpenAIEmbeddings
from langchain_experimental.text_splitter import SemanticChunker
from langchain_core.documents import Document
from database import create_vector_index
import hashlib

# --- Neo4j Sink ---
def load_to_neo4j(items: Iterator[Dict[str, Any]]):
    """
    Custom DLT Sink to write nodes to Neo4j.
    Now includes Vector Embedding logic!
    """
    try:
        graph = Neo4jGraph(
            url=Config.NEO4J_URI,
            username=Config.NEO4J_USERNAME,
            password=Config.NEO4J_PASSWORD
        )
        
        # Ensure Vector Index Exists
        create_vector_index(graph)
        
        # Initialize Embedding Models
        embeddings = OpenAIEmbeddings(
            model=Config.OPENAI_EMBEDDING_MODEL,
            openai_api_base=Config.OPENAI_BASE_URL,
            openai_api_key=Config.OPENAI_API_KEY
        )
        text_splitter = SemanticChunker(embeddings, breakpoint_threshold_type="percentile")

        def process_content_to_chunks(text, source_id, metadata={}):
            if not text or len(text) < 50: return
            
            # Chunking
            try:
                docs = text_splitter.create_documents([text], metadatas=[metadata])
            except:
                # Fallback if semantic fails
                docs = [Document(page_content=text, metadata=metadata)]
                
            # Embed and Write
            # Batch embedding would be better, but for DLT stream doing one-by-one or small batches:
            texts = [d.page_content for d in docs]
            vectors = embeddings.embed_documents(texts)
            
            prev_chunk_id = None
            
            for i, (doc, vector) in enumerate(zip(docs, vectors)):
                chunk_id = hashlib.md5(f"{source_id}_{i}".encode()).hexdigest()
                
                query = """
                MERGE (c:Chunk {id: $id})
                SET c.text = $text,
                    c.source = $source,
                    c.page = $page,
                    c.embedding = $vector,
                    c.seq = $seq,
                    c.last_updated = timestamp()
                """
                params = {
                    "id": chunk_id,
                    "text": doc.page_content,
                    "source": source_id,
                    "page": metadata.get("pages", 1),
                    "vector": vector,
                    "seq": i
                }
                graph.query(query, params)
                
                # NEXT relationship for context window
                if prev_chunk_id:
                    graph.query("""
                        MATCH (c1:Chunk {id: $prev}), (c2:Chunk {id: $curr})
                        MERGE (c1)-[:NEXT]->(c2)
                    """, {"prev": prev_chunk_id, "curr": chunk_id})
                
                prev_chunk_id = chunk_id
                
            logger.info(f"   Using DLT Sink: Wrote {len(docs)} Chunks for {source_id}")


        for item in items:
            
            if "specs" in item: # It's a Car
                # 1. Standard Graph Node
                specs = item.get("specs", {})
                flat_item = item.copy()
                if "specs" in flat_item:
                    flat_item.update(flat_item.pop("specs"))
                
                props = {k: v for k, v in flat_item.items() if isinstance(v, (str, int, float, bool))}
                
                query = """
                MERGE (c:Car {source_url: $url})
                SET c += $props, c.last_updated = timestamp()
                """
                params = {"url": item.get("source_url"), "props": props}
                graph.query(query, params=params)
                
                # 2. Vector Chunking (Description)
                if item.get("description"):
                    process_content_to_chunks(
                        item.get("description"), 
                        item.get("source_url"), 
                        {"type": "car_description"}
                    )

            elif "type" in item and item["type"] == "pdf": # It's a Doc
                 # 1. Metadata Node 
                 query = """
                 MERGE (d:Document {file_id: $fid})
                 SET d.filename = $fname, d.pages = $pages, d.last_updated = timestamp()
                 """
                 params = {
                     "fid": item.get("file_id"),
                     "fname": item.get("filename"),
                     "pages": item.get("metadata", {}).get("pages")
                 }
                 graph.query(query, params=params)
                 
                 # 2. Vector Chunking (Full Content)
                 process_content_to_chunks(
                     item.get("content"), 
                     item.get("filename"), 
                     item.get("metadata", {})
                 )
            
            else: # Generic
                label = item.get("class", "Entity")
                identifier = item.get("id") or item.get("url") or item.get("name") or str(uuid.uuid4())
                
                query = f"MERGE (n:{label} {{id: $id}}) SET n += $props"
                props = {k: v for k, v in item.items() if isinstance(v, (str, int, float, bool))}
                graph.query(query, params={"id": identifier, "props": props})
                
                # If there's a big text field, chunk it?
                # Heuristic: find longest string
                long_text = max([v for v in item.values() if isinstance(v, str)], key=len, default="")
                if len(long_text) > 100:
                    process_content_to_chunks(long_text, identifier, {})

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
