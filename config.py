import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # Neo4j Config
    NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USERNAME = os.getenv('NEO4J_USERNAME', 'neo4j')
    NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

    # OpenAI Config
    OPENAI_API_KEY = os.getenv('OpenAi_api_key') or os.getenv('OPENAI_API_KEY')
    OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL', 'https://aigateway.ntictsolution.com/v1')
    OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
    OPENAI_EMBEDDING_MODEL = os.getenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-large')

    # Application Config
    FLASK_ENV = os.getenv('FLASK_ENV', 'production')
    PORT = int(os.getenv('PORT', 8000))
    
    # RAG Config
    RERANKER_METHOD = os.getenv("RERANKER_METHOD", "cross-encoder").lower()
    COHERE_API_KEY = os.getenv('COHERE_API_KEY')
    USER_AGENT = os.getenv('USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    
    # Paths
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    LOG_DIR = os.path.join(BASE_DIR, 'log')
    SESSION_FILE = os.path.join(DATA_DIR, 'chat_sessions.json')
    TRUST_CONFIG_FILE = os.path.join(DATA_DIR, 'source_config.json')

    @classmethod
    def validate(cls):
        """Validates critical configuration."""
        missing = []
        if not cls.NEO4J_PASSWORD: missing.append("NEO4J_PASSWORD")
        if not cls.OPENAI_API_KEY: missing.append("OPENAI_API_KEY")
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

Config.validate()
