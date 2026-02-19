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
        Args:
            file_path: Path to file.
            strategy: 'dlt' or 'native'.
        """
        ingestor = cls._strategies.get(strategy)
        if not ingestor:
            logger.warning(f"Unknown strategy '{strategy}', falling back to DLT.")
            ingestor = cls._strategies["dlt"]
            
        return ingestor.ingest_document(file_path)

    @classmethod
    def ingest_url(cls, url: str, strategy: str = "dlt"):
        """
        Ingests a URL using the selected strategy.
        Args:
            url: URL to crawl.
            strategy: 'dlt' or 'native'.
        """
        ingestor = cls._strategies.get(strategy)
        if not ingestor:
            logger.warning(f"Unknown strategy '{strategy}', falling back to DLT.")
            ingestor = cls._strategies["dlt"]
            
        return ingestor.ingest_url(url)
