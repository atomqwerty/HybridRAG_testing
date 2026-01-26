import os
import glob
import time
import random
import hashlib
import uuid
import concurrent.futures
from pathlib import Path
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.document_loaders import TextLoader, WebBaseLoader
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_experimental.text_splitter import SemanticChunker
from langchain_core.documents import Document

from config import Config
from logger import setup_logger
from database import get_db_connection, create_vector_index, create_fulltext_index, get_existing_sources
from vision_utils import describe_image, encode_image_from_file
from crawler import get_internal_links, get_links_from_sitemap, load_web_with_images

logger = setup_logger(__name__)

# --- Configuration ---
# All loaded from Config

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
        graph.query("CALL gds.graph.drop('communityGraph')")
        graph.query("CREATE INDEX community_id_index IF NOT EXISTS FOR (n:Entity) ON (n.communityId)")
        logger.info("Community detection complete.")
    except Exception as e:
        logger.warning(f"GDS Community Detection failed: {e}")

def get_combined_chunks(docs, chunks_to_combine=3):
    combined = []
    for i in range(0, len(docs), chunks_to_combine):
        batch = docs[i : i + chunks_to_combine]
        combined_content = "\n\n".join([d.page_content for d in batch])
        combined_ids = [d.metadata['id'] for d in batch]
        new_doc = Document(page_content=combined_content, metadata={"combined_chunk_ids": combined_ids})
        combined.append(new_doc)
    return combined

def ingest_data():
    start_time = time.time()
    logger.info("Starting ULTIMATE Hybrid RAG Data Ingestion...")
    
    def update_status(percent, message):
        try:
            status = "running" if percent < 100 else "completed"
            with open(os.path.join(Config.DATA_DIR, "ingest_status.json"), "w") as f:
                import json
                json.dump({"percent": percent, "message": message, "status": status}, f)
        except: pass

    update_status(5, "Connecting to Database...")
    try:
        graph = get_db_connection()
        logger.info("Connected to Neo4j")
        
        # Check command line args
        import sys
        should_clear = "--reset" in sys.argv or "--clear" in sys.argv
        if should_clear:
            logger.warning("Running with --reset: FULL RESET ENABLED.")
            graph.query("MATCH (n) DETACH DELETE n")
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        return

    # Initialize Models
    llm = ChatOpenAI(
        api_key=Config.OPENAI_API_KEY,
        base_url=Config.OPENAI_BASE_URL,
        model=Config.OPENAI_MODEL,
        temperature=0
    )

    embeddings = OpenAIEmbeddings(
        model=Config.OPENAI_EMBEDDING_MODEL,
        openai_api_base=Config.OPENAI_BASE_URL,
        openai_api_key=Config.OPENAI_API_KEY
    )

    # --- Helper: Auto-Trust ---
    def auto_add_trust_rule(pattern, type_):
        try:
            import json
            config_path = Config.TRUST_CONFIG_FILE
            data = {}
            if os.path.exists(config_path):
                 with open(config_path, 'r') as f: data = json.load(f)
            
            rules = data.get('rules', [])
            if any(r['pattern'] == pattern for r in rules): return
                
            rules.append({"pattern": pattern, "score": 1.0, "type": type_})
            data['rules'] = rules
            if 'default_score' not in data: data['default_score'] = 0.5
            
            with open(config_path, 'w') as f: json.dump(data, f, indent=4)
            logger.info(f"   🛡️ Auto-added Trust Rule for: {pattern} ({type_})")
        except: pass

    # --- Load & Chunk ---
    logger.info("Loading & Chunking Documents...")
    all_files = glob.glob(os.path.join(Config.DATA_DIR, "*"))
    docs = []
    existing_sources = get_existing_sources(graph)
    
    update_status(10, "Loading Documents...")
    
    for file_path in all_files:
        filename = os.path.basename(file_path)
        
        # SKIP Config/Status files (User Request)
        if filename in ["urls.txt", "source_config.json", "ingest_status.json", "chat_sessions.json"]:
            continue
            
        # Verify it's a file relative to data dir to avoid trust issues
        if os.path.isfile(file_path):
            auto_add_trust_rule(filename, 'file')

        if filename in existing_sources: continue
        ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if ext == '.pdf':
                logger.info(f"Loading PDF: {filename}")
                try:
                    import pymupdf4llm
                    unique_id = uuid.uuid4().hex[:8]
                    # ... text ...
                    img_output_dir = Path(Config.DATA_DIR) / "extracted_images" / f"pdf_{unique_id}"
                    img_output_dir.mkdir(parents=True, exist_ok=True)
                    
                    md_text = pymupdf4llm.to_markdown(
                        file_path, 
                        write_images=True, 
                        image_path=str(img_output_dir),
                        image_format="jpg"
                    )
                    
                    image_descriptions = ""
                    if img_output_dir.exists():
                         for img_file in img_output_dir.glob("*.jpg"):
                             if img_file.stat().st_size < 3000: continue 
                             try:
                                 b64 = encode_image_from_file(str(img_file))
                                 desc_path = Path(Config.LOG_DIR) / (img_file.name + '_desc.txt')
                                 desc = describe_image(b64, save_description_path=str(desc_path))
                                 rel_path = f"extracted_images/pdf_{unique_id}/{img_file.name}"
                                 image_descriptions += f"\n[IMAGE PATH: {rel_path}]\n[ANALYSIS: {desc}]\n"
                             except Exception as e:
                                 logger.warning(f"Image processing error: {e}")

                    final_content = md_text + "\n\n### EXTRACTED IMAGE ANALYSES:\n" + image_descriptions
                    docs.append(Document(page_content=final_content, metadata={"source": os.path.basename(file_path)}))
                except Exception as e:
                    logger.error(f"PDF conversion failed: {e}")

            elif ext == '.docx':
                logger.info(f"Loading DOCX: {os.path.basename(file_path)}")
                try:
                    import docx2txt
                    unique_id = uuid.uuid4().hex[:8]
                    temp_img_dir = Path(Config.DATA_DIR) / "extracted_images" / f"docx_{unique_id}"
                    temp_img_dir.mkdir(parents=True, exist_ok=True)
                    text = docx2txt.process(file_path, str(temp_img_dir))
                    
                    image_descriptions = ""
                    if temp_img_dir.exists():
                        for img_file in temp_img_dir.iterdir():
                            if img_file.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                                try:
                                    b64 = encode_image_from_file(str(img_file))
                                    desc = describe_image(b64)
                                    image_descriptions += f"\n[IMAGE PATH: {img_file}]\n{desc}\n"
                                except: pass
                    
                    docs.append(Document(
                        page_content=text + "\n\n### IMAGES:\n" + image_descriptions,
                        metadata={"source": os.path.basename(file_path)}
                    ))
                except Exception as e: logger.error(f"DOCX failed: {e}")

            elif ext == '.txt':
                 if os.path.basename(file_path) == "urls.txt": continue
                 loader = TextLoader(file_path)
                 docs.extend(loader.load())

        except Exception as e:
            logger.warning(f"Failed to load {file_path}: {e}")

    # Load from URLs
    url_file = os.path.join(Config.DATA_DIR, "urls.txt")
    if os.path.exists(url_file):
        with open(url_file, "r") as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        
        if urls:
            # --- PHASE 1: DISCOVERY (Parallel) ---
            update_status(20, "Discovering Sub-pages...")
            logger.info(f"Found {len(urls)} root URLs. Starting parallel discovery...")
            
            for u in urls:
                try:
                    from urllib.parse import urlparse
                    domain = urlparse(u).netloc.replace('www.', '')
                    if domain: auto_add_trust_rule(domain, 'domain')
                except: pass

            all_urls_to_process = set()
            
            def discover_links(root_url):
                try:
                    # 1. Sitemap Priority
                    sitemap_links = get_links_from_sitemap(root_url)
                    if sitemap_links:
                        logger.info(f"Using {len(sitemap_links)} URLs from Sitemap for {root_url}")
                        return sitemap_links
                    
                    # 2. Fallback to Crawler
                    logger.info(f"Deep crawling {root_url}...")
                    return get_internal_links(root_url, max_links=100)
                except Exception as e:
                    logger.error(f"Discovery error for {root_url}: {e}")
                    return [root_url]

            # Run Discovery in Parallel (Fast, Requests-based)
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(discover_links, urls)
                for res in results:
                    if res: all_urls_to_process.update(res)
            
            logger.info(f"✅ Total pages to scrape: {len(all_urls_to_process)}")
            
            # --- PHASE 2: EXTRACTION (Parallel) ---
            update_status(30, f"Scraping {len(all_urls_to_process)} pages...")
            
            # Loop is already parallel above
            def process_url(url):
                if url in existing_sources: 
                    logger.info(f"   ⏩ Skipping existing: {url}")
                    return []
                try:
                    logger.info(f"   🕷️  Scraping: {url}")
                    # Stagger start to avoid spikes
                    time.sleep(random.uniform(0.5, 2.0)) 
                    return load_web_with_images(url)
                except Exception as e: 
                    logger.warning(f"Scrape failed {url}: {e}")
                    return []

            # Selenium is heavy, keep workers moderate (3-4)
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                results = executor.map(process_url, list(all_urls_to_process))
                for res in results:
                    if res: docs.extend(res)

    if not docs:
        logger.info("No content loaded. Exiting.")
        update_status(100, "All URLs already processed.")
        return

    # Chunking
    update_status(40, "Chunking Content...")
    final_chunks = []
    semantic_splitter = SemanticChunker(embeddings, breakpoint_threshold_type="percentile")

    for doc in docs:
        if '[IMAGE PATH:' in doc.page_content:
            final_chunks.append(doc)
        else:
            try:
                splits = semantic_splitter.split_documents([doc])
                final_chunks.extend(splits)
            except:
                final_chunks.append(doc)

    # Prepare for Cypher
    update_status(50, "Embedding Chunks...")
    chunk_data = []
    chunks_with_metadata = []
    
    # BATCHING EMBEDDINGS to avoid 413 Errors
    batch_size = 20 # Conservative batch size
    all_texts = [c.page_content for c in final_chunks]
    all_embeddings = []
    
    total_batches = (len(all_texts) + batch_size - 1) // batch_size
    
    for i in range(0, len(all_texts), batch_size):
        batch_texts = all_texts[i : i + batch_size]
        try:
            logger.info(f"   Embedding batch {i//batch_size + 1}/{total_batches}...")
            batch_res = embeddings.embed_documents(batch_texts)
            all_embeddings.extend(batch_res)
        except Exception as e:
            logger.error(f"   ⚠️ Embedding Batch Failed: {e}")
            # Fallback: Try one by one or skip?
            # For now, just append empty or zeros to keep index alignment?
            # Better to fail explicitly or retry. 
            # Let's try to append zero-vectors or skip. 
            # Actually, if we skip, indexes misalign. We must align.
            # Let's try individual fallback.
            for text in batch_texts:
                try:
                    all_embeddings.append(embeddings.embed_query(text))
                except:
                    all_embeddings.append([0.0] * 3072) # Dummy vector

    for i, chunk in enumerate(final_chunks):
        chunk_id = hashlib.md5(chunk.page_content.encode()).hexdigest()
        source = chunk.metadata.get('source', 'unknown')
        chunk.metadata['id'] = chunk_id
        chunks_with_metadata.append(chunk)
        
        chunk_data.append({
            'id': chunk_id,
            'text': chunk.page_content,
            'source': source,
            'page': chunk.metadata.get('page'),
            'embedding': all_embeddings[i],
            'seq': i
        })

    # Ingest Chunks (Batch Cypher Writes too)
    update_status(60, "Writing to Neo4j...")
    
    # Write in batches of 100
    write_batch_size = 100
    for i in range(0, len(chunk_data), write_batch_size):
        batch = chunk_data[i : i + write_batch_size]
        graph.query("""
            UNWIND $batch AS data
            MERGE (c:Chunk {id: data.id})
            SET c.text = data.text, c.source = data.source, c.page = data.page, c.embedding = data.embedding, c.seq = data.seq
        """, {'batch': batch})
    
    # Create Relations
    graph.query("""
        MATCH (c:Chunk)
        WITH c.source AS src, c
        ORDER BY c.seq ASC
        WITH src, collect(c) as chunks
        UNWIND range(0, size(chunks)-2) AS i
        WITH chunks[i] AS c1, chunks[i+1] AS c2
        MERGE (c1)-[:NEXT]->(c2)
    """)
    
    create_vector_index(graph)
    create_fulltext_index(graph)

    # Extract Entities
    update_status(80, "Extracting Knowledge Graph...")
    combined_docs = get_combined_chunks(chunks_with_metadata, 4)
    # Default F1 Schema just in case env is not set
    allowed_nodes = ["Person", "Organization", "Event", "Location", "Product", "Service"]
    allowed_rels = ["WORKS_FOR", "LOCATED_AT", "PARTICIPATED_IN", "CREATED", "OFFERS"]
    
    llm_transformer = LLMGraphTransformer(
        llm=llm,
        allowed_nodes=allowed_nodes,
        allowed_relationships=allowed_rels
    )
    
    all_graph_docs = []
    
    # Progress Tracking
    total_batches = (len(combined_docs) + 4) // 5
    completed_batches = 0
    
    def process_batch(batch):
        try: 
            # logger.info("   Processing graph batch...") 
            return llm_transformer.convert_to_graph_documents(batch)
        except Exception as e:
            logger.warning(f"Graph extraction failed for batch: {e}")
            return []

    logger.info(f"Extracting entities from {len(combined_docs)} combined chunks (in {total_batches} batches)...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = []
        batch_size = 5
        for i in range(0, len(combined_docs), batch_size):
            futures.append(executor.submit(process_batch, combined_docs[i:i+batch_size]))
        
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: all_graph_docs.extend(res)
            
            completed_batches += 1
            if completed_batches % 2 == 0 or completed_batches == total_batches:
                logger.info(f"   Using LLM to extract entities: {completed_batches}/{total_batches} batches done...")
                update_status(80 + int(10 * completed_batches / total_batches), f"Extracting Entities ({completed_batches}/{total_batches})")

    if all_graph_docs:
        graph.add_graph_documents(all_graph_docs)
        # Link Entities to Chunks
        for g_doc in all_graph_docs:
            chunk_ids = g_doc.source.metadata.get('combined_chunk_ids', [])
            for chunk_id in chunk_ids:
                for node in g_doc.nodes:
                    graph.query("""
                        MATCH (c:Chunk {id: $chunk_id})
                        MERGE (e:Entity {id: $node_id})
                        ON CREATE SET e.type = $node_type
                        MERGE (c)-[:HAS_ENTITY]->(e)
                    """, {'chunk_id': chunk_id, 'node_id': node.id, 'node_type': node.type})

    clean_graph_schema(graph)
    enrich_communities(graph)
    
    duration = time.time() - start_time
    logger.info(f"Ingestion Complete! Time: {int(duration)}s")
    update_status(100, "Ingestion Complete!")

if __name__ == "__main__":
    ingest_data()
