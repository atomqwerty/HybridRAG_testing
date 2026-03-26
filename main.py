from app import create_app
from app.config import Config
from app.run_qa import initialize_reranker
import logging

# Setup Logger
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    try:
        # Preload Models
        initialize_reranker()
        
        # Create App
        app = create_app()
        
        # Start Server
        logger.info(f"🚀 Starting RAG API Server on port {Config.PORT}...")
        app.run(host='0.0.0.0', debug=(Config.FLASK_ENV == 'development'), port=Config.PORT, use_reloader=False)
        
    except Exception as e:
        logger.critical(f"🔥 FATAL ERROR STARTING APP: {e}", exc_info=True)
