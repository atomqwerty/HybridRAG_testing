import os
import shutil
import json
import logging
from app.config import Config


logger = logging.getLogger(__name__)


class FileService:
    """Service to handle file uploads, deletions, and ingestion."""

    @staticmethod
    def list_files():
        """Lists files in DATA_DIR recursively (skips derived folders)."""
        try:
            files = []
            if not os.path.exists(Config.DATA_DIR):
                return files

            # Names to ignore (case-insensitive)
            exclude = {"urls.txt", "url.txt", "source_config.json", "ingest_status.json", "chat_sessions.json", "crawl_history.json"}

            # Walk recursively but skip bulky or derived folders like dlt_output and extracted_images
            skip_dirs = {"dlt_output", "extracted_images"}

            for root, dirs, filenames in os.walk(Config.DATA_DIR):
                # Determine relative root from DATA_DIR
                rel_root = os.path.relpath(root, Config.DATA_DIR)
                parts = [] if rel_root in ('.', os.curdir) else rel_root.split(os.sep)
                # If any part of the path is a skip dir, don't traverse into it
                if any(part in skip_dirs for part in parts):
                    dirs[:] = [d for d in dirs if d not in skip_dirs]
                    continue

                for f in filenames:
                    if f.startswith('.'):
                        continue
                    if f.lower() in exclude:
                        continue
                    # Build a relative path so the frontend can preserve folder structure
                    if rel_root == '.' or rel_root == os.curdir:
                        rel_path = f
                    else:
                        rel_path = os.path.join(rel_root, f)
                    files.append(rel_path)

            # Sort for deterministic ordering
            files.sort()
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
        """Wipes Neo4j, local artifacts, and resets Trust Rules config."""
        try:
            from app.database import get_db_connection
            graph = get_db_connection()
            graph.query("MATCH (n) DETACH DELETE n")

            # Clear Data Dir (keep .json config files but reset sessions)
            if os.path.exists(Config.DATA_DIR):
                for f in os.listdir(Config.DATA_DIR):
                    if f.endswith('.json'): continue  # Keep config/sessions
                    p = os.path.join(Config.DATA_DIR, f)
                    if os.path.isfile(p): os.remove(p)
                    elif os.path.isdir(p): shutil.rmtree(p)

            # Also reset Trust Rules config so UI reflects clean state
            trust_config = {
                "strict_mode": True,
                "rules": [],
                "default_score": 0.5
            }
            with open(Config.TRUST_CONFIG_FILE, 'w') as f:
                json.dump(trust_config, f, indent=4)

            return {"status": "success", "message": "Database, artifacts, and Trust Rules cleared."}
        except Exception as e:
            logger.error(f"Clear DB failed: {e}")
            raise e
