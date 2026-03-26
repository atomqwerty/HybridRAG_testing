import sys
import os

# Add project root to sys path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.ingest_service import IngestService
from app.config import Config
import logging

# Setup minimal logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_crawler():
    """Reads data/urls.txt and ingests each URL."""
    urls_file = os.path.join(Config.DATA_DIR, "urls.txt")
    if not os.path.exists(urls_file):
        urls_file = os.path.join(Config.DATA_DIR, "url.txt")
    
    if not os.path.exists(urls_file):
        logger.error(f"Generate data/urls.txt or url.txt first! File not found.")
        return

    with open(urls_file, "r") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    logger.info(f"Checking {len(urls)} URLs from {os.path.basename(urls_file)}...")
    
    for url in urls:
        if "example.com" in url: continue
        try:
            logger.info(f"Crawling {url}...")
            IngestService.ingest_url(url, strategy="dlt")
        except Exception as e:
            logger.error(f"Failed to crawl {url}: {e}")

if __name__ == "__main__":
    run_crawler()
