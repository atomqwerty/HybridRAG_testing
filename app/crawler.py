import os
import requests
import uuid
import time
import shutil
import xml.etree.ElementTree as ET
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import json
import io
from langchain_core.documents import Document
from app.vision_utils import describe_image, encode_image_from_file
from app.config import Config
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image
from urllib.parse import unquote

def get_retry_session(auth_cookies=None):
    session = requests.Session()
    if auth_cookies and isinstance(auth_cookies, dict):
        requests.utils.add_dict_to_cookiejar(session.cookies, auth_cookies)
        
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

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

# ---------------------------------------------------------------------------
# Navigation / chrome stripping
# ---------------------------------------------------------------------------

# HTML tags that are purely structural chrome (no body content)
_NAV_TAGS = ["header", "footer", "nav", "aside", "menu", "menubar"]

# role= attribute values that indicate navigation widgets
_NAV_ROLES = {
    "banner", "navigation", "complementary", "contentinfo",
    "menubar", "menu", "toolbar", "search",
}

# CSS class substrings commonly used for navbars / menus
_NAV_CLASS_KEYWORDS = [
    "navbar", "nav-bar", "nav-menu", "navmenu",
    "header", "site-header", "top-bar", "topbar",
    "menu", "main-menu", "mega-menu", "megamenu",
    "sidebar", "side-bar", "breadcrumb",
    "footer", "site-footer", "bottom-bar",
    "cookie", "consent", "popup", "modal", "overlay",
    "social-share", "share-bar",
    "skip-link", "skip-nav",
]

# aria-label substrings that indicate navigation regions
_NAV_ARIA_LABELS = [
    "navigation", "main menu", "site menu", "header", "footer",
    "breadcrumb", "social", "cookie",
]


# ID substrings that indicate container elements are nav/menu chrome
# e.g.  id="wb_ResponsiveMenu1",  id="site-header",  id="main-nav"
_NAV_ID_KEYWORDS = [
    "nav", "menu", "navbar", "header", "footer",
    "topbar", "top-bar", "sidebar", "breadcrumb",
    "cookie", "consent", "overlay", "modal",
]


def _strip_navigation(soup: BeautifulSoup) -> None:
    """
    Removes all header/nav/menu/footer chrome from a BeautifulSoup tree in-place.
    Applies five passes:
      0. id= attribute keywords  (catches wb_ResponsiveMenu1, site-header, …)
      1. Tag name (header, nav, aside, footer, menu …)
      2. role= attribute (role="navigation", role="menu", …)
      3. CSS class keywords (navbar, topbar, sidebar, …)
      4. aria-label keywords
    After all passes, orphaned <input type=checkbox> and <label> toggle
    widgets (used by mobile menus) are also removed.
    """
    # Pass 0 — id attribute keywords
    # e.g. <div id="wb_ResponsiveMenu1"> or <div id="site-header">
    for el in soup.find_all(attrs={"id": True}):
        if el.parent is None:  # already removed by a previous decompose
            continue
        el_id = el.get("id", "").lower()
        if any(kw in el_id for kw in _NAV_ID_KEYWORDS):
            el.decompose()

    # Pass 1 — tags
    for tag_name in _NAV_TAGS + ["script", "style", "noscript", "iframe"]:
        for el in soup.find_all(tag_name):
            if el.parent is None:
                continue
            el.decompose()

    # Pass 2 — role attribute
    for el in soup.find_all(attrs={"role": True}):
        if el.parent is None:
            continue
        if el.get("role", "").strip().lower() in _NAV_ROLES:
            el.decompose()

    # Pass 3 — CSS classes
    for el in soup.find_all(attrs={"class": True}):
        if el.parent is None:
            continue
        classes = " ".join(el.get("class", [])).lower()
        if any(kw in classes for kw in _NAV_CLASS_KEYWORDS):
            el.decompose()

    # Pass 4 — aria-label
    for el in soup.find_all(attrs={"aria-label": True}):
        if el.parent is None:
            continue
        label = el.get("aria-label", "").lower()
        if any(kw in label for kw in _NAV_ARIA_LABELS):
            el.decompose()

    # Cleanup — remove <input type="checkbox"> toggle widgets (mobile menus)
    for el in soup.find_all("input", attrs={"type": "checkbox"}):
        if el.parent is None:
            continue
        el.decompose()


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

def get_internal_links(base_url, max_links=200, depth=1, timeout=10, user_agent=None, respect_robots_txt=True, verify_ssl=True, rate_limit_delay=0, auth_cookies=None):
    """
    Recursively crawls find internal links up to specified depth.
    """
    print(f"   🕷️ Deep Crawling ({depth} Levels) starting at: {base_url}")
    
    headers = {
        "User-Agent": user_agent or Config.USER_AGENT
    }

    if respect_robots_txt:
        try:
            from urllib.robotparser import RobotFileParser
            parsed_root = urlparse(base_url)
            rp = RobotFileParser()
            rp.set_url(f"{parsed_root.scheme}://{parsed_root.netloc}/robots.txt")
            rp.read()
            if not rp.can_fetch(headers["User-Agent"], base_url):
                print(f"      🚫 robots.txt disallows crawling: {base_url}")
                return [base_url]
        except Exception as e:
            print(f"      ⚠️ robots.txt check failed: {e}")
    
    found_links = set([base_url])
    queue = [(base_url, 0)] # URL, current_depth
    visited = set()
    session = get_retry_session(auth_cookies)
    
    while queue and len(found_links) < max_links:
        current_url, curr_depth = queue.pop(0)
        
        if current_url in visited or curr_depth >= depth + 1:
            continue
        
        visited.add(current_url)
        print(f"   🕷️  Crawling Sub-Page (Level {curr_depth}): {current_url}")
        
        try:
            if rate_limit_delay > 0:
                time.sleep(rate_limit_delay)
                
            response = session.get(current_url, headers=headers, timeout=timeout, verify=verify_ssl)
            if response.status_code != 200:
                print(f"      ⚠️ Failed to fetch (Status {response.status_code}): {current_url}")
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Strip headers, navbars, footers and other chrome
            _strip_navigation(soup)
            
            domain = urlparse(base_url).netloc
            elements = soup.find_all("a")
            print(f"      Found {len(elements)} <a> tags.")
            
            for elem in elements:
                try:
                    href = elem.get("href")
                    if not href: continue
                    
                    full_url = urljoin(current_url, href)
                    # Strip fragment
                    full_url = full_url.split('#')[0]
                    # Strip trailing slash for consistency
                    full_url = full_url.rstrip('/')
                    
                    parsed = urlparse(full_url)
                    
                    base_domain = domain.replace("www.", "")
                    link_domain = parsed.netloc.replace("www.", "")
                    
                    if base_domain not in link_domain: 
                        continue
                    
                    # Filter noise
                    path = parsed.path.lower()
                    noise = ['cart', 'login', 'facebook', 'line', 'tel:', 'mailto:', 'javascript', 'index.html']
                    if any(x in path or x in full_url.lower() for x in noise): 
                        continue
                    
                    if full_url not in found_links:
                        # Check robots.txt for sub-url if requested
                        if respect_robots_txt and 'rp' in locals():
                             if not rp.can_fetch(headers["User-Agent"], full_url):
                                 print(f"      🚫 robots.txt disallows: {full_url}")
                                 continue

                        found_links.add(full_url)
                        print(f"      + Queued: {full_url}")
                        if len(found_links) >= max_links: break
                        
                        if curr_depth < depth:
                            queue.append((full_url, curr_depth + 1))
                            
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

def load_web_with_images(url, driver=None, selectors=None, wait_time=2, javascript_enabled=True, timeout=10, user_agent=None, verify_ssl=True, extract_entities=False, auth_cookies=None):
    """
    Scrapes a page using Selenium (if JS enabled) or Requests.
    Supports custom selectors for focused data extraction.
    """
    print(f"   - Scraping: {url} (JS: {javascript_enabled})")
    
    html_content = ""
    soup = None
    
    if javascript_enabled:
        should_quit_driver = False
        if driver is None:
            driver = init_driver(user_agent=user_agent)
            should_quit_driver = True
        
        if driver:
            try:
                driver.get(url)
                # If auth cookies exist, add them to selenium and refresh
                if auth_cookies and isinstance(auth_cookies, dict):
                    for name, value in auth_cookies.items():
                        driver.add_cookie({"name": name, "value": value})
                    driver.get(url) # reload with cookies
                    
                # Wait for custom time
                time.sleep(wait_time)
                
                # Optional: Scroll for lazy loading
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                html_content = driver.page_source
                soup = BeautifulSoup(html_content, 'html.parser')
            except Exception as e:
                print(f"      ❌ Selenium failed for {url}: {e}")
            finally:
                if should_quit_driver:
                    driver.quit()
    
    if not soup: # Fallback or JS disabled
        try:
            print(f"      ⚠️ Using Requests for {url}")
            headers = {"User-Agent": user_agent or Config.USER_AGENT}
            session = get_retry_session(auth_cookies)
            response = session.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
            if response.status_code == 200:
                html_content = response.text
                soup = BeautifulSoup(html_content, 'html.parser')
        except Exception as e:
            print(f"      ❌ Scrape failed for {url}: {e}")
            return []

    if not soup:
        return []

    # 1. Custom Selectors Logic
    main_content_area = None
    if selectors:
        for selector in selectors:
            try:
                found = soup.select_one(selector)
                if found:
                    main_content_area = found
                    print(f"      🎯 Found content via selector: {selector}")
                    break
            except Exception as e:
                print(f"      ⚠️ Invalid selector {selector}: {e}")

    # 2. Extract Images
    images = soup.find_all('img')
    image_descriptions = ""
    candidates = []
    for img in images:
        src = img.get('src') or img.get('data-src')
        if not src: continue
        if src.startswith("data:image"): continue
        full_url = urljoin(url, src)
        if any(x in full_url.lower() for x in ['icon', 'button', 'social', 'footer', 'thumb']): continue
        candidates.append(full_url)

    valid_images = []
    for full_url in list(set(candidates))[:10]:
        try:
            img_resp = requests.get(full_url, stream=True, timeout=5, verify=verify_ssl)
            if img_resp.status_code == 200:
                content = img_resp.content
                size = len(content)
                if size > 5 * 1024:
                    ctype = (img_resp.headers.get('Content-Type') or '').lower()
                    to_write = None
                    ext = 'jpg'

                    # Detect SVG/vector graphics and attempt conversion to PNG if cairosvg is available.
                    is_svg = False
                    if 'svg' in ctype or content.lstrip().startswith(b'<?xml') or b'<svg' in content[:200].lower():
                        is_svg = True

                    if is_svg:
                        try:
                            import cairosvg
                            png_bytes = cairosvg.svg2png(bytestring=content)
                            # validate result
                            Image.open(io.BytesIO(png_bytes)).verify()
                            to_write = png_bytes
                            ext = 'png'
                        except Exception as e:
                            print(f"      ⚠️ Skipping SVG or unsupported vector at {full_url}: {e}")
                            continue
                    else:
                        # Validate raster image bytes with PIL
                        try:
                            Image.open(io.BytesIO(content)).verify()
                            to_write = content
                            ext = 'jpg'
                        except Exception:
                            print(f"      ⚠️ Skipping non-image or corrupted file at {full_url} (Content-Type: {ctype})")
                            continue

                    img_filename = f"web_{uuid.uuid4().hex[:8]}.{ext}"
                    img_path = Path(Config.DATA_DIR) / "extracted_images" / img_filename
                    img_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(img_path, "wb") as f:
                        f.write(to_write)
                    valid_images.append((len(to_write), img_path, full_url))
        except Exception as e:
            print(f"      ⚠️ Failed to fetch or validate image {full_url}: {e}")
            continue

    valid_images.sort(key=lambda x: x[0], reverse=True)
    top_images = valid_images[:2]

    for _, img_path, full_url in top_images:
        try:
            b64 = encode_image_from_file(str(img_path))
            if not b64:
                print(f"      ⚠️ Skipping image {img_path} because it could not be encoded/compressed")
                continue
            desc = describe_image(b64, save_description_path=None)
            file_name = img_path.name
            rel_img_path = f"/api/images/{file_name}"
            image_descriptions += f"\n[IMAGE PATH: {rel_img_path}]\n[SOURCE URL: {full_url}]\n{desc}\n"
        except Exception as e:
            print(f"      ⚠️ Error processing image {img_path}: {e}")
            continue

    # 3. Clean and Extract Text
    content_source = main_content_area if main_content_area else soup
    # Strip all navigation/chrome from the chosen content area
    _strip_navigation(content_source)
        
    text = content_source.get_text(separator='\\n')
    lines = (line.strip() for line in text.splitlines())
    clean_text = '\\n'.join(line for line in lines if line)
    
    full_content = f"Source URL: {url}\\n\\n{clean_text}\\n\\n### IMAGES:\\n{image_descriptions}"
    
    meta = {
        "source": url, 
        "title": soup.title.string if soup.title else url,
        "image_path": top_images[0][1].name if top_images else "default.jpg"
    }
    
    if extract_entities:
        emails = list(set(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', clean_text)))
        phones = list(set(re.findall(r'\+?\d{1,4}?[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}', clean_text)))
        meta["extracted_emails"] = emails
        meta["extracted_phones"] = [p for p in phones if len(p) >= 10]
        
    return [Document(
        page_content=full_content,
        metadata=meta
    )]
