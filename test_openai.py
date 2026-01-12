import os
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings, ChatOpenAI

# Load environment variables
load_dotenv()

OPENAI_API_KEY = os.getenv('OpenAi_api')
OPENAI_EMB_KEY = os.getenv('OpenAi_api_embbeding') or OPENAI_API_KEY
OPENAI_BASE_URL = 'https://aigateway.ntictsolution.com/v1'

def test_api():
    print("🧪 Testing OpenAI API Config...")
    print(f"   Base URL: {OPENAI_BASE_URL}")
    print(f"   API Key: {OPENAI_API_KEY[:5]}...{OPENAI_API_KEY[-5:] if OPENAI_API_KEY else 'NONE'}")

    # 1. Test Chat Completion (LLM)
    print("\n💬 1. Testing Chat Completion (gpt-4o)...")
    try:
        llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            model='gpt-4o',
            temperature=0
        )
        response = llm.invoke("Hello, say 'API Working'!")
        print(f"   ✅ Success! Response: {response.content}")
    except Exception as e:
        print(f"   ❌ Chat Completion Failed: {e}")

    # 2. Test Embeddings (Large)
    print("\n🧠 2. Testing Embeddings (text-embedding-3-large)...")
    try:
        embeddings = OpenAIEmbeddings(
            model='text-embedding-3-large',
            openai_api_base=OPENAI_BASE_URL,
            openai_api_key=OPENAI_EMB_KEY
        )
        vector = embeddings.embed_query("This is a test sentence.")
        print(f"   ✅ Success! Vector Dimension: {len(vector)}")
    except Exception as e:
        print(f"   ❌ Embedding Failed: {e}")

if __name__ == "__main__":
    test_api()
