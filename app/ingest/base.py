from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseIngestor(ABC):
    """Abstract Base Class for Ingestion Strategies."""

    @abstractmethod
    def ingest_document(self, file_path: str, source_type: str = "file") -> Dict[str, Any]:
        """
        Ingests a single document.
        Args:
            file_path (str): Path to the file.
            source_type (str): Type of source (e.g., 'pdf', 'file').
        Returns:
            Dict: Result status/message.
        """
        pass

    @abstractmethod
    def ingest_url(self, url: str) -> Dict[str, Any]:
        """
        Ingests a URL (Generic Crawl).
        Args:
            url (str): The URL to crawl.
        Returns:
            Dict: Result status/message.
        """
        pass
