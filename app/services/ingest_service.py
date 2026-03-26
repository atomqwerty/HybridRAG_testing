import os
import time
from app.ingest.dlt_ingest import DLTIngestor
from app.ingest.native_ingest import NativeIngestor
import logging

logger = logging.getLogger(__name__)

class IngestService:
    """Facade for Ingestion Strategies."""
    
    _strategies = {
        "dlt": DLTIngestor(),
        "native": NativeIngestor()
    }
    
    @classmethod
    def ingest_document(cls, file_path: str, strategy: str = "dlt"):
        """
        Ingests a document using the selected strategy.
        Special Case: If it's a url.txt or urls.txt, it triggers crawling for each URL.
        """
        start_time = time.time()
        filename = os.path.basename(file_path).lower()
        
        try:
            if filename in ("url.txt", "urls.txt"):
                logger.info(f"📍 Detected URL list file: {file_path}. Intercepting for crawler...")
                with open(file_path, 'r') as f:
                    urls = [line.strip() for line in f if line.strip() and line.strip().startswith(('http://', 'https://'))]
                
                if not urls:
                    logger.warning(f"No valid URLs found in {file_path}")
                    return {"status": "skipped", "message": "No valid URLs found"}
                
                logger.info(f"🚀 Triggering ingestion for {len(urls)} URLs from {file_path}...")
                results = []
                for url in urls:
                    results.append(cls.ingest_url(url, strategy=strategy))
                
                duration = time.time() - start_time
                logger.info(f"⏱️ Total time for URL list ingestion ({filename}): {duration:.2f} seconds")
                return {"status": "success", "message": f"Processed {len(urls)} URLs from {filename}", "details": results}

            ingestor = cls._strategies.get(strategy)
            if not ingestor:
                logger.warning(f"Unknown strategy '{strategy}', falling back to DLT.")
                ingestor = cls._strategies["dlt"]
                
            res = ingestor.ingest_document(file_path)
            duration = time.time() - start_time
            logger.info(f"⏱️ Total time for document ingestion ({filename}): {duration:.2f} seconds")
            return res

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"❌ Ingestion failed after {duration:.2f}s for {file_path}: {e}")
            raise e

    @classmethod
    def ingest_url(cls, url: str, strategy: str = "dlt"):
        """
        Ingests a URL using the selected strategy.
        """
        start_time = time.time()
        ingestor = cls._strategies.get(strategy)
        if not ingestor:
            logger.warning(f"Unknown strategy '{strategy}', falling back to DLT.")
            ingestor = cls._strategies["dlt"]
            
        try:
            res = ingestor.ingest_url(url)
            duration = time.time() - start_time
            logger.info(f"⏱️ Total time for URL ingestion ({url}): {duration:.2f} seconds")
            return res
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"❌ URL Ingestion failed after {duration:.2f}s for {url}: {e}")
            raise e
