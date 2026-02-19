import os
import requests
import uuid
import time
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import json
from langchain_core.documents import Document
from app.vision_utils import describe_image, encode_image_from_file
from app.config import Config
from PIL import Image
from urllib.parse import unquote

# --- CONFIG LOADER ---
DEFAULTS = {
    "brands": [], # User should populate this in source_config.json
    "keywords": ['product', 'detail', 'spec', 'model', 'feature', 'category'],
    "exclude": ['login', 'cart', 'account', 'register', 'policy', 'terms', 'privacy']
} 

def get_crawler_rules():
    """Loads dynamic brands/keywords from JSON, falls back to defaults."""
    try:
        config_path = Path("source_config.json")
        if config_path.exists():
            with open(config_path, "r") as f:
                data = json.load(f)
                config = data.get("crawler_config")
                return config if config is not None else DEFAULTS
    except Exception as e:
        print(f"⚠️ Error loading crawler config: {e}")
    return DEFAULTS
# ---------------------

# Import ChromeDriverManager only if needed or assume installed
# from webdriver_manager.chrome import ChromeDriverManager 
# (We are using system installed chromedriver at /usr/bin/chromedriver)

def clean_extracted_images():
    """Cleans up old extracted images and logs before fresh ingestion."""
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

def get_internal_links(base_url, max_links=200):
    """
    Recursively crawls up to 3 levels deep to find car model pages.
    Uses 'requests' (curl-like) for speed, replacing Selenium.
    """
    print(f"   🕷️ Deep Crawling (3 Levels) starting at: {base_url} (Using Requests/Curl)")
    
    headers = {
        "User-Agent": Config.USER_AGENT
    }
    
    found_links = set([base_url])
    queue = [(base_url, 0)] # URL, Depth
    visited = set()
    
    while queue and len(found_links) < max_links:
        current_url, depth = queue.pop(0)
        
        if current_url in visited or depth >= 4:
            continue
        
        visited.add(current_url)
        print(f"   🕷️  Crawling Sub-Page (Level {depth}): {current_url}")
        
        try:
            # Use requests instead of Selenium
            response = requests.get(current_url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"      ⚠️ Failed to fetch (Status {response.status_code}): {current_url}")
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # --- SKIP HEADER/FOOTER/NAV to prevent crawling menus ---
            for tag_name in ["header", "footer", "nav", "aside"]:
                for tag in soup.find_all(tag_name):
                    tag.decompose()
            
            # Remove by class/id keywords
            noise_keywords = ["menu", "navigation", "footer", "header", "sidebar", "copyright", "contact"]
            for tag in soup.find_all(True):
                if not hasattr(tag, 'attrs') or tag.attrs is None: continue # Safety Check
                classes = str(tag.get("class", "")) + " " + str(tag.get("id", ""))
                if any(x in classes.lower() for x in noise_keywords):
                    tag.decompose()
            # --------------------------------------------------------
            
            domain = urlparse(base_url).netloc
            elements = soup.find_all("a")
            print(f"      Found {len(elements)} <a> tags.")
            
            for elem in elements:
                try:
                    href = elem.get("href")
                    if not href: continue
                    
                    full_url = urljoin(current_url, href)
                    parsed = urlparse(full_url)
                    
                    # Normalize domain (ignore www.)
                    base_domain = domain.replace("www.", "")
                    link_domain = parsed.netloc.replace("www.", "")
                    
                    # DEBUG: Print all candidates
                    # print(f"      ? Checking: {full_url}")

                    if base_domain not in link_domain: 
                        # print(f"      - Ignored (External): {full_url}")
                        continue
                    
                    # Filter noise (Minimal - Only strictly useless links)
                    path = parsed.path.lower()
                    noise = ['cart', 'login', 'facebook', 'line', 'tel:', 'mailto:', 'javascript', '#', 'review', 'news', 'blog', 'index.html']
                    if any(x in path or x in full_url.lower() for x in noise): 
                        continue
                    
                    # --- SMART CAR FILTER ---
                    # The user wants "only car links". We use Brand & Keyword matching.
                    rules = get_crawler_rules()
                    if not rules: rules = DEFAULTS # Double safety
                    brands = rules.get("brands", [])
                    keywords = rules.get("keywords", [])
                    
                    link_text = elem.get_text().lower().strip()
                    url_lower = full_url.lower()
                    
                    is_car_link = False
                    
                    # 1. Check URL for brands/models
                    if any(b in url_lower for b in brands): is_car_link = True
                    if any(k in url_lower for k in keywords): is_car_link = True
                    
                    # 2. Check Anchor Text for brands
                    if any(b in link_text for b in brands): is_car_link = True
                    
                    # In Generic Mode, every link is a "car link" unless excluded
                    is_car_link = True
                    
                    # If it's NOT a car link, skip it (unless we are at root level, where we might need to navigate categories)
                    # But user asked for "only car link".
                    if not is_car_link and depth > 0:
                        # Assuming root page links to categories which link to cars. 
                        # If we are strictly "only car links", we might miss categories. 
                        # But typically car links are direct.
                        continue
                        
                    if full_url not in found_links:
                        found_links.add(full_url)
                        print(f"      + Queued (Car/Model): {full_url}")
                        
                        queue.append((full_url, depth + 1))
                    else:
                         # print(f"      - Ignored (Duplicate): {full_url}")
                         pass
                            
                except Exception:
                    continue
                        
        except Exception as e:
            print(f"      ⚠️ Failed to crawl {current_url}: {e}")
    
    print(f"   ✅ Found {len(found_links)} total pages to scrape.")
    return list(found_links)

def get_links_from_sitemap(root_url):
    """
    BEST PRACTICE: Fetch URLs directly from sitemap.xml
    This is much cleaner than crawling html links.
    """
    
    # Try common sitemap locations
    sitemap_paths = ["sitemap.xml", "Result/sitemap.xml", "sitemap_index.xml"]
    
    base_domain = f"{urlparse(root_url).scheme}://{urlparse(root_url).netloc}"
    
    found_urls = set()
    
    for path in sitemap_paths:
        sitemap_url = urljoin(base_domain, path)
        print(f"   🗺️  Checking Sitemap: {sitemap_url} ...")
        
        try:
            resp = requests.get(sitemap_url, timeout=10)
            if resp.status_code == 200:
                print(f"      ✅ Found Sitemap!")
                # Parse XML
                try:
                    root = ET.fromstring(resp.content)
                    # Namespace map might be needed for standard sitemaps
                    # Usually tags are like {http://www.sitemaps.org/schemas/sitemap/0.9}loc
                    # We'll just search for 'loc' regardless of namespace
                    
                    count = 0
                    for elem in root.iter():
                        if 'loc' in elem.tag:
                             url = elem.text.strip()
                             # Apply our Car Brand Filter immediately
                             if is_relevant_car_url(url):
                                 found_urls.add(url)
                                 count += 1
                                 
                    print(f"      extracted {count} relevant car URLs from sitemap.")
                    if count > 0:
                        return list(found_urls) # Return immediately if found
                        
                except Exception as e:
                    print(f"      ⚠️ XML Parse Error: {e}")
                    
        except Exception:
            pass
            
    return []

def is_relevant_car_url(url):
    """Helper to filter URLs for Cars"""
    url = url.lower()
    
    # Explicit Skip
    noise = ['cart', 'login', 'facebook', 'line', 'tel:', 'mailto:', 'javascript', '#', 'index.html']
    if any(x in url for x in noise): return False
    
    # Brands & Keywords & Excludes
    rules = get_crawler_rules()
    excludes = rules.get("exclude", [])

    # Check Excludes first
    if any(ex in url for ex in excludes): return False
    
    # Generic Mode: Follow ALL internal links (except excluded ones)
    return True

def init_driver():
    """Initializes a headless Chrome driver."""
    print("DEBUG: Initializing Shared Chrome Driver...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(f"user-agent={Config.USER_AGENT}")
    
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        print(f"❌ Failed to init driver: {e}")
        return None

def load_web_with_images(url, driver=None):
    """
    Uses Selenium (RPA) to render the page, scroll for lazy loading,
    and extract high-fidelity text and images.
    """
    print(f"   - Scraping (RPA/Selenium): {url}")
    
    should_quit_driver = False
    if driver is None:
        print(f"DEBUG: No shared driver provided. Creating new one for {url}")
        driver = init_driver()
        should_quit_driver = True
    
    if not driver:
        return [] # Fail if no driver
        
    try:
        try:
            driver.get(url)  
            # ... (Rest of logic uses 'driver')
            
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
            if should_quit_driver:
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
            
            # Filter noise keywords in URL (Removed 'logo' as requested)
            if any(x in full_url.lower() for x in ['icon', 'button', 'social', 'footer', 'thumb', 'thumbnail']): 
                continue
                
            candidates.append(full_url)

        # 2. Download and Filter by Size (Get the "Meatier" content)
        valid_images = [] # List of (size_in_bytes, local_path, source_url)
        MAX_CANDIDATES_CHECK = 20 # OPTIMIZATION: Reduced from 100 to 20 for speed
        
        print(f"      🔎 Scanning {len(candidates)} images (checking top {MAX_CANDIDATES_CHECK})...")
        
        for full_url in list(set(candidates))[:MAX_CANDIDATES_CHECK]:
            try:
                img_resp = requests.get(full_url, stream=True, timeout=3)
                if img_resp.status_code != 200: continue
                
                size = len(img_resp.content)
                # SMART FILTER: Ignore small icons/logos (< 5KB, was 15KB)
                if size < 5 * 1024: 
                    print(f"      - Rejected small file size ({size} bytes): {full_url}")
                    continue
            
                # BLACKLIST: Ignore known generic images
                decoded_url = unquote(full_url.lower())
                if "home-charging" in decoded_url or "line-add" in decoded_url:
                    print(f"      - Skipping Blacklisted Image: {full_url}")
                    continue

                # --- NEW: Check Dimensions (Resolution Filter) ---
                suffix = Path(full_url).suffix
                if not suffix or suffix.lower() not in ['.jpg', '.png', '.jpeg', '.webp']:
                    suffix = '.jpg'
                    
                img_filename = f"web_{uuid.uuid4().hex[:8]}{suffix}"
                save_dir = Path(Config.DATA_DIR) / "extracted_images"
                save_dir.mkdir(parents=True, exist_ok=True)
                img_path = save_dir / img_filename
                
                with open(img_path, "wb") as f:
                    f.write(img_resp.content)
                    
                # Skip SVGs
                if img_path.suffix.lower() == '.svg': 
                    continue

                # --- NEW: Check Dimensions (Resolution Filter) ---
                try:
                    with Image.open(img_path) as im:
                        w, h = im.size
                        # Reject if too small (thumbnail size like 300x163)
                        # We want Hero Images > 250x200
                        # We want Hero Images > 200x150
                        if w < 200 or h < 150:
                            # print(f"      - Rejected small image ({w}x{h}): {full_url}")
                            continue
                except Exception:
                    # If PIL cannot open it, it's likely corrupt
                    continue
                # -----------------------------------------------

                print(f"      ✅ Accepted Image: {full_url} ({size} bytes, {w}x{h})")
                valid_images.append((size, img_path, full_url))
                
            except Exception as e:
                print(f"      ❌ Image Error {full_url}: {e}")
                continue
        
        # 3. Sort by Size (Descending) -> Largest images differ likely to be Main Content/Diagrams
        valid_images.sort(key=lambda x: x[0], reverse=True)
        
        # 4. Select Images (Top 2 Large Images)
        top_images = valid_images[:2] # Compromise: fast but gets cover + detail
        print(f"      🏆 Selected {len(top_images)} valid images >2KB for analysis.")

        # 5. Analyze with Vision
        for _, img_path, full_url in top_images:
            try:
                print(f"      📸 Analyzed Web Image: {os.path.basename(full_url)[:30]}...")
                b64 = encode_image_from_file(str(img_path))
                
                # Save description (DISABLED LOGGING)
                # log_dir = Path("log")
                # log_dir.mkdir(parents=True, exist_ok=True)
                # desc_path = log_dir / (img_path.stem + '_description.txt')
                
                # Pass None to save_description_path to avoid file creation
                desc = describe_image(b64, save_description_path=None)
                # Store path relative to project root for frontend serving
                rel_img_path = str(img_path).replace("\\", "/") # Ensure forward slashes
                image_descriptions += f"\\n[IMAGE PATH: {rel_img_path}]\\n[SOURCE URL: {full_url}]\\n{desc}\\n"
                
            except Exception as e:
                print(f"      ⚠️ Vision analysis failed: {e}")
                
        # 2. Extract Text
        # 2. Extract Text - SMART CLEANING (Reduce Trash Data)
        
        # A. Remove Standard Noise Tags
        # (Re-enabling header/footer removal to fix "trash data" complaint)
        noise_tags = ["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "iframe", "svg"]
        for tag in soup(noise_tags):
            tag.decompose()
            
        # Remove breadcrumbs specifically (User Request)
        for tag in soup.find_all(True, {"class": True}):
             try:
                 classes = tag.get("class", [])
                 if isinstance(classes, str): classes = [classes]
                 if any("breadcrumb" in c.lower() for c in classes):
                     tag.decompose()
             except: pass
            
        # B. Remove elements by Class/ID (Menus, Sidebars, Popups, Footers)
        trash_keywords = ['menu', 'sidebar', 'nav', 'cookie', 'advert', 'popup', 'social', 'share', 'newsletter', 'footer', 'copyright', 'contact', 'facebook']
        for tag in soup.find_all(True):
            try:
                if not hasattr(tag, 'attrs') or tag.attrs is None: continue
                # Check classes AND IDs
                classes = str(tag.get("class", "")) + " " + str(tag.get("id", ""))
                
                if any(k in classes.lower() for k in trash_keywords):
                    tag.decompose()
            except: pass
            
        # C. Remove elements by Text Content (Copyright, etc.)
        text_trash = ["copyright ©", "all rights reserved", "working days/hours"]
        for tag in soup.find_all(['div', 'span', 'p', 'footer']):
            try:
                txt = tag.get_text().lower()
                if any(x in txt for x in text_trash) and len(txt) < 300: # Safety: Don't delete long articles
                     # Only delete if it seems like a footer block (short text)
                     tag.decompose()
            except: pass
            
        # C. Focus on Main Content (if available) - This eliminates 90% of wrapper trash
        main_content_area = soup.find('main') or soup.find('article') or soup.find('div', id='content') or soup.find('div', class_='content')
        
        # If we found a specific main area, use it. Otherwise use the cleaned soup.
        content_source = main_content_area if main_content_area else soup
            
        text = content_source.get_text(separator='\\n')
        
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\\n'.join(line for line in lines if line)
        
        # Combine
        full_content = f"Source URL: {url}\\n\\n{clean_text}\\n\\n### DETECTED IMAGES FROM WEBPAGE:\\n{image_descriptions}"
        
        # FINAL CLEAN: Remove Markdown Bolding (User Request)
        full_content = full_content.replace("**", "").replace("__", "")
        
        # --- Log Scraped Content (DISABLED) ---
        # try:
        #     log_dir = Path("log")
        #     log_dir.mkdir(parents=True, exist_ok=True)
        #     # Create simple filename
        #     sanitized_name = url.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "")[:50]
        #     log_file = log_dir / f"web_scraped_{sanitized_name}_{uuid.uuid4().hex[:6]}.txt"
        #     
        #     with open(log_file, "w", encoding="utf-8") as f:
        #         f.write(full_content)
        #     print(f"      📝 Scraped content saved to: {log_file}")
        # except Exception as e:
        #     print(f"      ⚠️ Failed to save web log: {e}")
        # ---------------------------
        
        print(f"   ✅ CRAWLED: {url}")
        
        # 3. Determine Best Image (Cover) for the UI
        best_image_path = "default.jpg"
        if top_images:
             # top_images is list of (_, path, url)
             # Get filename: web_xxxx.jpg
             best_image_path = top_images[0][1].name
             print(f"      🖼️ Selected Best Cover Image: {best_image_path}")

        return [Document(
            page_content=full_content,
            metadata={
                "source": url, 
                "title": soup.title.string if soup.title else url,
                "image_path": best_image_path # <-- NEW: Pass to DLT sink
            }
        )]
        
    except Exception as e:
        print(f"      ❌ Web Scraping (Selenium) failed for {url}: {e}")
        # Fallback to Requests (Static Scraping)
        try:
            print("      ⚠️ Attempting Fallback to Requests (Static HTML)...")
            response = requests.get(url, headers={'User-Agent': Config.USER_AGENT}, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                text = soup.get_text(separator='\\n')
                # Clean up whitespace
                lines = (line.strip() for line in text.splitlines())
                clean_text = '\\n'.join(line for line in lines if line)
                
                full_content = f"Source URL: {url}\\n(Fallback Scraping)\\n\\n{clean_text}"
                return [Document(
                    page_content=full_content,
                    metadata={"source": url, "title": soup.title.string if soup.title else url}
                )]
        except Exception as e2:
             print(f"      ❌ Fallback failed too: {e2}")
        
        return []
