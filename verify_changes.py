import sys
import os
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def verify_imports():
    print("Testing imports...")
    try:
        import config
        print("✅ config setup")
        import logger
        print("✅ logger setup")
        import api
        print("✅ api setup")
        import run_qa
        print("✅ run_qa setup")
        import ingest_graph
        print("✅ ingest_graph setup")
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Setup failed: {e}")
        sys.exit(1)

def verify_config():
    print("\nTesting Config...")
    from config import Config
    print(f"   NEO4J_URI: {Config.NEO4J_URI}")
    print(f"   OPENAI_BASE_URL: {Config.OPENAI_BASE_URL}")
    print(f"   LOG_DIR: {Config.LOG_DIR}")
    
    if not Config.OPENAI_API_KEY:
        print("⚠️  Warning: OPENAI_API_KEY is missing.")
    else:
        print("✅ OPENAI_API_KEY present")

def verify_logger():
    print("\nTesting Logger...")
    from logger import setup_logger
    log = setup_logger("test_logger")
    log.info("Test log message")
    print("✅ Logger initialized")

if __name__ == "__main__":
    verify_imports()
    verify_config()
    verify_logger()
    print("\n🎉 Verification Complete!")
