
import os
import sys
from langchain_community.graphs import Neo4jGraph
from langchain_openai import OpenAIEmbeddings, ChatOpenAI

# Add project root to sys path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.config import Config
from app.run_qa import hybrid_context, get_graph

def test_retrieval_context():
    graph = get_graph()
    embeddings = OpenAIEmbeddings(
         model=Config.OPENAI_EMBEDDING_MODEL, 
         openai_api_base=Config.OPENAI_BASE_URL,
         openai_api_key=Config.OPENAI_API_KEY
    )
    llm = ChatOpenAI(
        api_key=Config.OPENAI_API_KEY,
        base_url=Config.OPENAI_BASE_URL,
        model=Config.OPENAI_MODEL,
        temperature=0
    )
    
    question = "ข้อมูลการชาร์จ Xpeng G6 Long Range RWD"
    print(f"Testing retrieval for: {question}")
    
    context = hybrid_context(graph, embeddings, question, llm_model=llm, route="fast_fact")
    
    print("\n--- RETRIEVED CONTEXT ---")
    print(context)
    print("--- END CONTEXT ---\n")
    
    # Check if [IMAGE PATH: ...] is in context
    if "[IMAGE PATH:" in context:
        print("✅ Image Path found in context!")
    else:
        print("❌ Image Path NOT found in context.")

if __name__ == "__main__":
    test_retrieval_context()
