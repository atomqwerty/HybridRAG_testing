from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import re

# Import the answer function from run_qa
import sys
sys.path.append(os.path.dirname(__file__))

# Load environment
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# Initialize Neo4j and models (same as run_qa.py)
NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')
OPENAI_API_KEY = os.getenv('OpenAi_api')
OPENAI_EMB_KEY = os.getenv('OpenAi_api_embbeding') or OPENAI_API_KEY
OPENAI_BASE_URL = 'https://aigateway.ntictsolution.com/v1'

graph = Neo4jGraph(
    url=NEO4J_URI,
    username=NEO4J_USERNAME,
    password=NEO4J_PASSWORD
)

llm = ChatOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    model='gpt-4o',
    temperature=0
)

embeddings = OpenAIEmbeddings(
    api_key=OPENAI_EMB_KEY,
    base_url=OPENAI_BASE_URL,
    model='text-embedding-3-large'
)

# Import functions from run_qa
from run_qa import hybrid_context, answer

# Store chat sessions (in production, use Redis or database)
chat_sessions = {}

@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Endpoint to handle chat messages
    Expected JSON: {"message": "user question", "session_id": "optional"}
    """
    try:
        data = request.json
        user_message = data.get('message', '')
        session_id = data.get('session_id', 'default')
        
        if not user_message:
            return jsonify({"error": "Message is required"}), 400
        
        # Get or create session history
        if session_id not in chat_sessions:
            chat_sessions[session_id] = ""
        
        history = chat_sessions[session_id]
        
        # Get answer (returns dict with result and context)
        output = answer(user_message, history=history)
        bot_response = output['result']
        context = output['context']
        
        # Update history
        chat_sessions[session_id] += f"User: {user_message}\nBot: {bot_response}\n"
        
        # Extract sources and images from the context (already retrieved!)
        # context = hybrid_context(graph, embeddings, user_message) <-- REMOVED DOUBLE CALL
        sources = re.findall(r"\[Source: (.*?), Page: (.*?)\]", context)
        image_paths = re.findall(r"\[IMAGE PATH: (.*?)\]", context)
        
        return jsonify({
            "response": bot_response,
            "sources": [{"file": src, "page": pg} for src, pg in sources],
            "images": image_paths
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/clear', methods=['POST'])
def clear_session():
    """Clear chat history for a session"""
    data = request.json
    session_id = data.get('session_id', 'default')
    if session_id in chat_sessions:
        chat_sessions[session_id] = ""
    return jsonify({"message": "Session cleared"})

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"})

@app.route('/images/<path:filename>')
def serve_image(filename):
    """Serve images from data directory"""
    # Remove 'data/' prefix if present in the path
    if filename.startswith('data/'):
        filename = filename[5:]
    
    # Serve from the data directory
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    return send_from_directory(data_dir, filename)

if __name__ == '__main__':
    print("🚀 Starting RAG API Server...")
    print("📡 API available at: http://localhost:5000")
    app.run(debug=True, port=5000)

#cd C:\Users\Dashboard\Downloads\HybridRAG_testing
#conda activate neo4j_rag
#python api.py