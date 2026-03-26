import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class Config:
    # Neo4j Config
    NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USERNAME = os.getenv('NEO4J_USERNAME', 'neo4j')
    NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

    # OpenAI Config
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    OPENAI_BASE_URL = os.getenv('BASE_URL', 'https://aigateway.ntictsolution.com/v1')
    OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

    # Embedding model
    OPENAI_EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', os.getenv('OPENAI_EMBEDDING_MODEL', 'Qwen3-Embedding-4B'))
    OPENAI_EMBEDDING_API_KEY = os.getenv('EMBEDDING_API_KEY', os.getenv('OPENAI_EMBEDDING_API_KEY', OPENAI_API_KEY))
    OPENAI_EMBEDDING_BASE_URL = os.getenv('OPENAI_EMBEDDING_BASE_URL', OPENAI_BASE_URL)

    # Application Config
    FLASK_ENV = os.getenv('FLASK_ENV', 'production')
    PORT = int(os.getenv('PORT', 8000))
    
    # RAG Config
    RERANKER_METHOD = os.getenv("RERANKER_METHOD", "cross-encoder").lower()
    COHERE_API_KEY = os.getenv('COHERE_API_KEY')
    USER_AGENT = os.getenv('USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    
    # Paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    LOG_DIR = os.path.join(BASE_DIR, 'log')
    SESSION_FILE = os.path.join(DATA_DIR, 'chat_sessions.json')
    TRUST_CONFIG_FILE = os.path.join(BASE_DIR, 'source_config.json')
    USERS_FILE = os.path.join(DATA_DIR, 'users.json')
    AUDIT_LOG_FILE = os.path.join(DATA_DIR, 'audit_log.json')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', f"sqlite:///{os.path.join(DATA_DIR, 'app.db')}")

    # Auth
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-me-in-production')
    TOKEN_EXPIRY_HOURS = int(os.getenv('TOKEN_EXPIRY_HOURS', '24'))

    # --- Vision RAG (Placeholder) ---
    # We use a fixed dimension for visual embeddings (e.g. 128) for future expansion.
    EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "2560"))

    # Visual boost multiplier used to prioritize vision/hybrid chunks when visual intent detected
    VISUAL_BOOST = float(os.getenv("VISUAL_BOOST", "0.25"))
    
    @classmethod
    def validate(cls):
        """Validates critical configuration and logs warnings if missing."""
        missing = []
        if not cls.NEO4J_PASSWORD: missing.append("NEO4J_PASSWORD")
        if not cls.OPENAI_API_KEY: missing.append("OPENAI_API_KEY")
        
        if missing:
            logger.warning(f"⚠️ Missing recommended environment variables: {', '.join(missing)}")
            # Instead of crashing, we log a warning. This helps debug in environments 
            # where vars might be passed differently (e.g. docker-compose .env).

Config.validate()
