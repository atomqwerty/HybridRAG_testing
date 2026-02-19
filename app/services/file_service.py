import os
import shutil
import json
import logging
from app.config import Config
from app.services.ingest_service import IngestService

logger = logging.getLogger(__name__)

class FileService:
    """Service to handle file uploads, deletions, and ingestion."""

    @staticmethod
    def upload_file(file, strategy: str = "dlt"):
        """Saves file and triggers ingestion."""
        if not file or file.filename == '':
            raise ValueError("No file selected")
            
        filename = file.filename
        file_path = os.path.join(Config.DATA_DIR, filename)
        
        # Save File
        file.save(file_path)
        logger.info(f"File saved to {file_path}")
        
        # Determine Type and Ingest
        try:
            # Using IngestService Facade
            # This runs ingestion synchronously (blocking). 
            # In a real app, this should be a background task (Celery/Redis Queue).
            IngestService.ingest_document(file_path, strategy=strategy)
            
            return {"status": "success", "message": f"Successfully ingested {filename} using {strategy}"}
        except Exception as e:
            logger.error(f"Ingestion failed: {e}")
            raise e

    @staticmethod
    def list_files():
        """Lists files in DATA_DIR."""
        try:
            files = []
            if os.path.exists(Config.DATA_DIR):
                for f in os.listdir(Config.DATA_DIR):
                    if os.path.isfile(os.path.join(Config.DATA_DIR, f)) and not f.startswith('.'):
                         files.append(f)
            return files
        except Exception as e:
            logger.error(f"List files failed: {e}")
            return []

    @staticmethod
    def delete_file(filename):
        """Deletes a file and its artifacts."""
        try:
            file_path = os.path.join(Config.DATA_DIR, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                
            # Also clean up extracted images folder?
            # Logic from api.py:
            base_name = os.path.splitext(filename)[0]
            img_dir = os.path.join(Config.DATA_DIR, "extracted_images", base_name)
            if os.path.exists(img_dir):
                shutil.rmtree(img_dir)
                
            return {"status": "success", "message": f"Deleted {filename}"}
        except Exception as e:
            logger.error(f"Delete file failed: {e}")
            raise e

    @staticmethod
    def clear_database():
        """Wipes Neo4j and local artifacts."""
        try:
            from app.database import get_db_connection
            graph = get_db_connection()
            graph.query("MATCH (n) DETACH DELETE n")
            
            # Clear Data Dir (except keep .keep files if any)
            # Logic from api.py is to verify what to keep.
            # Simplified:
            if os.path.exists(Config.DATA_DIR):
                for f in os.listdir(Config.DATA_DIR):
                    if f.endswith('.json'): continue # Keep config/sessions?
                    p = os.path.join(Config.DATA_DIR, f)
                    if os.path.isfile(p): os.remove(p)
                    elif os.path.isdir(p): shutil.rmtree(p)
            
            return {"status": "success", "message": "Database and artifacts cleared."}
        except Exception as e:
            logger.error(f"Clear DB failed: {e}")
            raise e
