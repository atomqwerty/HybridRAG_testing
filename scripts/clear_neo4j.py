import sys
import os
import argparse

# Add parent directory to sys.path to allow importing 'app'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# Add app directory to sys.path to allow internal imports in app module (e.g. 'from config import Config')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

from app.database import get_db_connection
from app.logger import setup_logger

logger = setup_logger("clear_db")

def clear_database():
    parser = argparse.ArgumentParser(description="Clear Neo4j Database")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if not args.force:
        print("⚠️  WARNING: This will delete ALL data in the Neo4j Database.")
        confirm = input("Are you sure? (type 'yes' to confirm): ")
        
        if confirm.lower() != 'yes':
            print("Operation cancelled.")
            return

    try:
        # We need to manually initialize the driver or use the extensive setup
        # But get_db_connection usually handles it.
        # Note: If running outside of the main app context, ensure ENV vars are set.
        
        logger.info("Connecting to Neo4j...")
        graph = get_db_connection()
        
        logger.info("Executing DETACH DELETE...")
        graph.query("MATCH (n) DETACH DELETE n")
        
        logger.info("✅ Database Cleared.")
        
        # Clear Trust Config (source_config.json is usually in app/ or root)
        # Check root first
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        config_path = os.path.join(root_dir, 'source_config.json')
        
        if os.path.exists(config_path):
            os.remove(config_path)
            logger.info("✅ Trust Rules (source_config.json) Deleted.")
        else:
            logger.info("ℹ️  No source_config.json found.")
            
    except Exception as e:
        logger.error(f"Failed to clear database: {e}")

if __name__ == "__main__":
    clear_database()
