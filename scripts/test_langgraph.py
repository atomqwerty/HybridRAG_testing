import sys
import os

# Add parent path to sys path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'app'))

from graph_agent import app_graph
from agents.supervisor import supervisor

def test_supervisor_and_table_agent():
    print("--- TESTING MULTI-AGENT RAG ---")
    
    # 1. Test Routing (Table Intent)
    q1 = "What is the battery capacity of BYD Atto 3?"
    print(f"\n[TEST 1] Query: {q1}")
    route1 = supervisor.route(q1)
    print(f"Supervisor Decision: {route1.intent.upper()} (Reason: {route1.reasoning})")
    
    if route1.intent == "table":
        print("✅ Correctly identified Table Intent.")
    else:
        print(f"❌ Failed: Expected 'table', got '{route1.intent}'")

    # 2. Test Routing (Text Intent)
    q2 = "How does the warranty coverage work for the powertrain?"
    print(f"\n[TEST 2] Query: {q2}")
    route2 = supervisor.route(q2)
    print(f"Supervisor Decision: {route2.intent.upper()} (Reason: {route2.reasoning})")
    
    if route2.intent == "text":
        print("✅ Correctly identified Text Intent.")
    else:
        print(f"❌ Failed: Expected 'text', got '{route2.intent}'")
        
    # 3. Test End-to-End Graph (Table Intent)
    print(f"\n[TEST 3] Running Graph for: {q1}")
    try:
        inputs = {"question": q1, "documents": [], "iterations": 0}
        result = app_graph.invoke(inputs)
        generation = result.get("generation", "")
        print(f"Final Answer: {generation}")
        
        if "[Table Agent]" in generation:
            print("✅ Graph successfully routed to Table Agent.")
        else:
             print("❌ Graph did not use Table Agent (missing prefix).")
             
    except Exception as e:
        print(f"❌ Graph Execution Failed: {e}")

if __name__ == "__main__":
    test_supervisor_and_table_agent()
