from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
from dotenv import load_dotenv
import re

# Import the answer function AND initializer from run_qa
from run_qa import answer, initialize_reranker
import sys
sys.path.append(os.path.dirname(__file__))

# Load environment
load_dotenv()

app = Flask(__name__, static_folder='frontend/build', static_url_path='/')
CORS(app)  # Enable CORS for React frontend

# Initialize Neo4j and models (same as run_qa.py)
NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')
OPENAI_API_KEY = os.getenv('OpenAi_api_key')
OPENAI_EMB_KEY = os.getenv('OpenAi_api_key')
OPENAI_BASE_URL = 'https://aigateway.ntictsolution.com/v1'

# OpenAI Configuration (for Embeddings if needed elsewhere, though run_qa handles it)
# Currently api.py handles routing, run_qa handles logic.

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
        temperature = data.get('temperature', 0)
        
        # Get answer (returns dict with result and context)
        output = answer(user_message, history=history, temperature=temperature)
        bot_response = output['result']
        context = output['context']
        
        # Update history
        chat_sessions[session_id] += f"User: {user_message}\nBot: {bot_response}\n"
        
        # Extract sources and images from the context (already retrieved!)
        # Extract sources and images from the context (already retrieved!)
        # Extract Sources & Images
        try:
            sources_list = re.findall(r"\[Source: (.*?), Page: (.*?)\]", context)
            
            # Extract and Limit Images (Max 2 Unique)
            raw_image_paths = re.findall(r"\[IMAGE PATH: (.*?)\]", context)
            unique_images = []
            seen_imgs = set()
            
            for img_p in raw_image_paths:
                try:
                    img_p = img_p.strip()
                    if img_p not in seen_imgs:
                        seen_imgs.add(img_p)
                        
                        # Fix path separators
                        norm_path = img_p.replace('\\', '/')
                        
                        # We want the path relative to 'data/'
                        # If path is 'data/extracted_images/foo.jpg' -> 'extracted_images/foo.jpg'
                        if 'data/' in norm_path:
                            # Split by 'data/' and take the last part
                            rel_path = norm_path.split('data/')[-1]
                        else:
                            # Fallback: just use the filename if path format is unexpected
                            rel_path = os.path.basename(norm_path)
                            # If it's an extracted image, prepending the folder might be guessing, 
                            # but usually safe if we know where they go.
                            if 'web_' in rel_path or 'extracted_' in rel_path:
                                rel_path = f"extracted_images/{rel_path}"
                                
                        unique_images.append(rel_path)
                except Exception as img_err:
                    print(f"⚠️ Error processing image path {img_p}: {img_err}")
                    continue
            
            # Limit images to 2
            final_images = unique_images[:2]
            
            # Extract Valid Sources (Max 3, No Images)
            valid_sources = []
            for src, pg in sources_list:
                if len(valid_sources) >= 3: break
                
                # Clean up source string
                src_clean = src.strip()
                
                # Skip if source looks like an image file
                if any(src_clean.lower().endswith(ext) for ext in ['.jpg', '.png', '.jpeg', '.webp']):
                    continue
                    
                valid_sources.append({"file": os.path.basename(src_clean), "page": pg})
                
        except Exception as parse_err:
            print(f"⚠️ Error parsing sources/images: {parse_err}")
            final_images = []
            valid_sources = []

        return jsonify({
            "response": bot_response,
            "sources": valid_sources,
            "images": final_images
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

@app.route('/')
def index():
    """Serve React App in Production"""
    if os.path.exists(app.static_folder):
        return send_from_directory(app.static_folder, 'index.html')
    else:
        return "<h1>✅ Hybrid RAG API is Running!</h1><p>Frontend build not found. Run 'npm run build' in frontend/ first.</p>"

@app.route('/<path:path>')
def serve_static(path):
    """Serve static files for React"""
    if os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        # Return index.html for client-side routing
        return send_from_directory(app.static_folder, 'index.html')

@app.route('/images/<path:filename>')
def serve_image(filename):
    """Serve images from data directory"""
    # Remove 'data/' prefix if present in the path
    if filename.startswith('data/'):
        filename = filename[5:]
    
    # Serve from the data directory
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    return send_from_directory(data_dir, filename)

import subprocess
import threading
import atexit
import sys

# Global variable to store the frontend process
frontend_process = None

def cleanup():
    """Kills the frontend process on shutdown"""
    global frontend_process
    if frontend_process:
        print("🛑 Stopping React Frontend...")
        # On Windows, we need to be aggressive to kill the process tree
        subprocess.call(['taskkill', '/F', '/T', '/PID', str(frontend_process.pid)])

def start_frontend():
    """Starts the React frontend in a separate thread"""
    global frontend_process
    print("🚀 Starting React Frontend...")
    frontend_dir = os.path.join(os.path.dirname(__file__), 'frontend')
    
    # Use shell=True for Windows compatibility
    frontend_process = subprocess.Popen('npm start', cwd=frontend_dir, shell=True)

if __name__ == '__main__':
    # Register cleanup to run when the script exits (Ctrl+C)
    atexit.register(cleanup)
    
    # Start frontend in background (ONLY IN DEV/WINDOWS)
    if os.name == 'nt' or os.environ.get('FLASK_ENV') == 'development':
        threading.Thread(target=start_frontend, daemon=True).start()
    else:
        print("🐧 Linux/Production Mode: Expecting React 'build' folder to be served.")
    
    print("🚀 Starting RAG API Server...")
    
    # Initialize Reranker (Load Model)
    initialize_reranker()
    
    print("📡 API available at: http://localhost:8000")
    try:
        # run on 0.0.0.0 for linux server access
        app.run(host='0.0.0.0', debug=True, port=8000, use_reloader=False)
    except KeyboardInterrupt:
        pass # Handle manual stop cleanly
    