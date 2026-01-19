import os
import glob
import time
import hashlib
import uuid
import hashlib
import uuid
import concurrent.futures
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
OPENAI_API_KEY = os.getenv('OpenAi_api_key')
OPENAI_EMB_KEY = os.getenv('OpenAi_api_key')
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

def get_internal_links(base_url, max_links=200):
    """
    Recursively crawls up to 2 levels deep to find car model pages.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    from urllib.parse import urljoin, urlparse
    import time

    print(f"   🕷️ Deep Crawling (2 Levels) starting at: {base_url}")
    
    # Setup Headless Chrome
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    
    found_links = set([base_url])
    queue = [(base_url, 0)] # URL, Depth
    visited = set()
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        while queue and len(found_links) < max_links:
            current_url, depth = queue.pop(0)
            
            if current_url in visited or depth >= 3:
                continue
            
            visited.add(current_url)
            print(f"      Scanning (Level {depth}): {current_url}")
            
            try:
                driver.get(current_url)
                time.sleep(3) # Wait for render (Increased for safety)
                
                domain = urlparse(base_url).netloc
                elements = driver.find_elements("tag name", "a")
                
                for elem in elements:
                    try:
                        href = elem.get_attribute("href")
                        if not href: continue
                        
                        full_url = urljoin(base_url, href)
                        parsed = urlparse(full_url)
                        
                        # Domain check
                        if parsed.netloc != domain: continue
                        
                        # Filter noise
                        path = parsed.path.lower()
                        noise = ['about', 'contact', 'cart', 'login', 'facebook', 'line', 'tel:', 'mailto:', 'javascript']
                        if any(x in path or x in full_url.lower() for x in noise): continue
                        
                        # Only add if it looks relevant (EV/Charger/Car)
                        is_relevant = any(k in full_url.lower() for k in ['ev', 'charger', 'car', 'model', 'spec', 'audi', 'benz', 'bmw', 'mg', 'volvo'])
                        if not is_relevant and depth > 0: continue
                        
                        if full_url not in found_links:
                            found_links.add(full_url)
                            # If it's a category/hub page, queue it for next level
                            # We assume pages with 'ev-charging' might have sub-models
                            if 'html' in path and depth < 2:
                                priority_score = 0
                                if any(x in path for x in ['2018', '2019', '2020', '2021', '2022', '2023', '2024', '2025']):
                                    priority_score = 2 # High priority (Specific Model Year)
                                elif any(x in path for x in ['spec', 'model']):
                                    priority_score = 1 # Medium priority
                                
                                # Insert based on priority (Pseudo-Priority Queue)
                                if priority_score > 0:
                                    queue.insert(0, (full_url, depth + 1))
                                else:
                                    queue.append((full_url, depth + 1))
                                
                    except Exception:
                         continue
                         
            except Exception as e:
                print(f"      ⚠️ Failed to crawl {current_url}: {e}")
                
        driver.quit()
        
    except Exception as e:
        print(f"   ⚠️ Crawler failed: {e}")
        
    print(f"   ✅ Found {len(found_links)} total pages to scrape.")
    return list(found_links)

def clean_extracted_images():
    """Cleans up old extracted images and logs before fresh ingestion."""
    import shutil
    
    print("🧹 Cleaning up old extracted images and logs...")
    
    # Clean Images
    img_dir = Path("data/extracted_images")
    if img_dir.exists():
        try:
            shutil.rmtree(img_dir)
            img_dir.mkdir(exist_ok=True)
            print("   ✅ Deleted old data/extracted_images/")
        except Exception as e:
            print(f"   ⚠️ Could not clean image dir: {e}")
            
    # Clean Logs (Optional, but good for debugging)
    log_dir = Path("log")
    if log_dir.exists():
         try:
            shutil.rmtree(log_dir)
            log_dir.mkdir(exist_ok=True)
            print("   ✅ Deleted old log/")
         except Exception as e:
             print(f"   ⚠️ Could not clean log dir: {e}")

def load_web_with_images(url):
    """
    Uses Selenium (RPA) to render the page, scroll for lazy loading,
    and extract high-fidelity text and images.
    """
    from bs4 import BeautifulSoup
    import requests # Keep requests for image downloading only
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    from urllib.parse import urljoin
    import time
    
    print(f"   - Scraping (RPA/Selenium): {url}")
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        try:
            driver.get(url)
            
            # --- RPA Action: Scroll to Bottom to trigger Lazy Loading ---
            print("      ↓ Auto-scrolling to trigger lazy content...")
            last_height = driver.execute_script("return document.body.scrollHeight")
            while True:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2) # Wait for page to load
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
            # -------------------------------------------------------------
            
            # Get fully rendered HTML
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
        finally:
            driver.quit()
        
        # 1. Extract Images (from the rendered Soup)
        images = soup.find_all('img')
        image_descriptions = ""
        
        # --- SMART SELECTION STRATEGY ---
        # 1. Collect potential candidates
        candidates = []
        for img in images:
            src = img.get('src') or img.get('data-src')
            if not src: continue
            if src.startswith("data:image"): continue
            
            full_url = urljoin(url, src)
            
            # Filter noise keywords in URL
            if any(x in full_url.lower() for x in ['logo', 'icon', 'button', 'social', 'footer']): 
                continue
                
            candidates.append(full_url)

        # 2. Download and Filter by Size (Get the "Meatier" content)
        valid_images = [] # List of (size_in_bytes, local_path, source_url)
        MAX_CANDIDATES_CHECK = 20 # Check up to 20 images to find the best ones
        
        print(f"      🔎 Scanning {len(candidates)} images to find the most important ones...")
        
        for full_url in list(set(candidates))[:MAX_CANDIDATES_CHECK]:
            try:
                img_resp = requests.get(full_url, stream=True, timeout=3)
                if img_resp.status_code != 200: continue
                
                size = len(img_resp.content)
                if size < 8000: continue # Skip small images (< 8KB) - likely spacers/icons
                
                # Save locally temporarily
                suffix = Path(full_url).suffix
                if not suffix or suffix.lower() not in ['.jpg', '.png', '.jpeg', '.webp']:
                    suffix = '.jpg'
                    
                img_filename = f"web_{uuid.uuid4().hex[:8]}{suffix}"
                save_dir = Path("data/extracted_images")
                save_dir.mkdir(parents=True, exist_ok=True)
                img_path = save_dir / img_filename
                
                with open(img_path, "wb") as f:
                    f.write(img_resp.content)
                    
                # Skip SVGs
                if img_path.suffix.lower() == '.svg': 
                    continue
                    
                valid_images.append((size, img_path, full_url))
                
            except:
                continue
        
        # 3. Sort by Size (Descending) -> Largest images differ likely to be Main Content/Diagrams
        valid_images.sort(key=lambda x: x[0], reverse=True)
        
        # 4. Select Top 5
        top_images = valid_images[:5]
        print(f"      🏆 Selected top {len(top_images)} largest images for analysis.")

        # 5. Analyze with Vision
        for _, img_path, full_url in top_images:
            try:
                print(f"      📸 Analyzed Web Image: {os.path.basename(full_url)[:30]}...")
                b64 = encode_image_from_file(str(img_path))
                
                # Save description
                log_dir = Path("log")
                log_dir.mkdir(parents=True, exist_ok=True)
                desc_path = log_dir / (img_path.stem + '_description.txt')
                
                desc = describe_image(b64, save_description_path=str(desc_path))
                image_descriptions += f"\n[IMAGE PATH: {img_path}]\n[SOURCE URL: {full_url}]\n{desc}\n"
                
            except Exception as e:
                print(f"      ⚠️ Vision analysis failed: {e}")
                
        # 2. Extract Text
        # Remove scripts and styles
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
            
        text = soup.get_text(separator='\n')
        
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\n'.join(line for line in lines if line)
        
        # Combine
        full_content = f"Source URL: {url}\n\n{clean_text}\n\n### DETECTED IMAGES FROM WEBPAGE:\n{image_descriptions}"
        
        # FINAL CLEAN: Remove Markdown Bolding (User Request)
        full_content = full_content.replace("**", "").replace("__", "")
        
        # --- Log Scraped Content ---
        try:
            log_dir = Path("log")
            log_dir.mkdir(parents=True, exist_ok=True)
            # Create simple filename
            sanitized_name = url.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "")[:50]
            log_file = log_dir / f"web_scraped_{sanitized_name}_{uuid.uuid4().hex[:6]}.txt"
            
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(full_content)
            print(f"      📝 Scraped content saved to: {log_file}")
        except Exception as e:
            print(f"      ⚠️ Failed to save web log: {e}")
        # ---------------------------
        
        return [Document(
            page_content=full_content,
            metadata={"source": url, "title": soup.title.string if soup.title else url}
        )]
        
    except Exception as e:
        print(f"      ❌ Web Scraping (Selenium) failed for {url}: {e}")
        return []

def ingest_data():
    start_time = time.time()
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
        model='gpt-4o-mini',
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
    start_time = time.time()
    
    # CLEANUP OLD DATA FIRST
    clean_extracted_images()
    
    docs = []
    
    # Process local files
    print("\n📂 Loading local files from data/ ...")
    
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
            print(f"   - Found {len(urls)} root URLs.")
            all_urls_to_process = set()
            
            # 1. Expand URLs (Crawl 1 level deep)
            for root_url in urls:
                sub_links = get_internal_links(root_url, max_links=10) # Crawl sub-pages
                all_urls_to_process.update(sub_links)
            
            print(f"   - Processing {len(all_urls_to_process)} total pages (Root + Sub-pages)...")
            
            # 2. Scrape Each
            for url in all_urls_to_process:
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
    # Process in Smaller Batches
    BATCH_SIZE = 5
    total_batches = (len(combined_docs) + BATCH_SIZE - 1) // BATCH_SIZE

    def process_batch(batch_idx):
        start = batch_idx * BATCH_SIZE
        end = start + BATCH_SIZE
        batch_combined = combined_docs[start:end]
        
        print(f"   - Processing Batch {batch_idx + 1}/{total_batches} ({len(batch_combined)} docs)...")
        try:
            return llm_transformer.convert_to_graph_documents(batch_combined)
        except Exception as e:
            print(f"      ⚠️ Batch {batch_idx + 1} failed: {e}")
            return []

    print(f"   🚀 Running Extraction in Parallel (4 Workers)...")
    
    all_graph_docs = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(process_batch, range(total_batches))
        for res in results:
            if res:
                all_graph_docs.extend(res)

    print(f"   ✅ Extraction Complete. Adding {len(all_graph_docs)} graph documents to Neo4j...")
    
    if all_graph_docs:
        graph.add_graph_documents(all_graph_docs)
        
        # Link Entities to ALL Source Chunks
        for g_doc in all_graph_docs:
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

    # --- 6. Post-Processing ---
    clean_graph_schema(graph)
    enrich_communities(graph)
    
    end_time = time.time()
    duration = end_time - start_time
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    
    print(f"\n🎉 Ultimate Ingestion Complete!")
    print(f"⏱️ Total Time Taken: {minutes}m {seconds}s")

if __name__ == "__main__":
    ingest_data()
