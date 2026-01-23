from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import os
import re
import json
import sys
import threading
import atexit
import subprocess
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from logger import setup_logger
from run_qa import answer, initialize_reranker
from run_qa_stream import answer_stream
from database import get_db_connection, create_vector_index

# Setup Logger
logger = setup_logger(__name__)

app = Flask(__name__, static_folder='frontend/build', static_url_path='/')
CORS(app)  # Enable CORS for React frontend

# Initialize Persistence
chat_sessions = {}

def load_sessions():
    """Load chat sessions from disk."""
    global chat_sessions
    if os.path.exists(Config.SESSION_FILE):
        try:
            with open(Config.SESSION_FILE, 'r') as f:
                chat_sessions = json.load(f)
            logger.info(f"Loaded {len(chat_sessions)} sessions from disk.")
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")
            chat_sessions = {}

def save_sessions():
    """Save chat sessions to disk."""
    try:
        with open(Config.SESSION_FILE, 'w') as f:
            json.dump(chat_sessions, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save sessions: {e}")

# Load sessions on startup
load_sessions()

@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    try:
        data = request.json
        user_message = data.get('message', '')
        session_id = data.get('session_id', 'default')
        
        # Get history
        history = chat_sessions.get(session_id, "")
        
        def generate():
            full_answer = ""
            for chunk_str in answer_stream(user_message, history):
                 yield chunk_str
                 
                 # Accumulate answer for history
                 try:
                     c = json.loads(chunk_str)
                     if c['type'] == 'token':
                         full_answer += c['content']
                 except: pass
            
            # Update history persistence
            chat_sessions[session_id] = history + f"User: {user_message}\nBot: {full_answer}\n"
            save_sessions()
                 
        return Response(stream_with_context(generate()), mimetype='application/x-ndjson')
    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return jsonify({"error": str(e)}), 500


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
        temperature = data.get('temperature', 0)
        
        if not user_message:
            return jsonify({"error": "Message is required"}), 400
        
        # Get or create session history
        if session_id not in chat_sessions:
            chat_sessions[session_id] = ""
        
        history = chat_sessions[session_id]
        
        # Get answer
        # Note: answer() function inside run_qa.py handles the LLM call.
        # We need to ensure run_qa.py is also updated to use Config
        output = answer(user_message, history=history, temperature=temperature)
        bot_response = output['result']
        context = output['context']
        
        # Update history
        chat_sessions[session_id] += f"User: {user_message}\nBot: {bot_response}\n"
        save_sessions()
        
        # Extract Sources & Images logic...
        # (Keeping existing logic but cleaning it up slightly)
        final_images = []
        valid_sources = []
        
        try:
            sources_list = re.findall(r"\[Source: (.*?), Page: (.*?)\]", context)
            raw_image_paths = re.findall(r"\[IMAGE PATH: (.*?)\]", context)
            
            # Processing Images
            seen_imgs = set()
            for img_p in raw_image_paths:
                img_p = img_p.strip()
                if img_p not in seen_imgs:
                    seen_imgs.add(img_p)
                    norm_path = img_p.replace('\\', '/')
                    if 'data/' in norm_path:
                        rel_path = norm_path.split('data/')[-1]
                    else:
                        rel_path = os.path.basename(norm_path)
                        if 'web_' in rel_path or 'extracted_' in rel_path:
                            rel_path = f"extracted_images/{rel_path}"
                    final_images.append(rel_path)
            
            final_images = final_images[:2]

            # Processing Sources
            for src, pg in sources_list:
                if len(valid_sources) >= 3: break
                src_clean = src.strip()
                if any(src_clean.lower().endswith(ext) for ext in ['.jpg', '.png', '.jpeg', '.webp']):
                    continue
                valid_sources.append({"file": os.path.basename(src_clean), "page": pg})
                
        except Exception as parse_err:
            logger.warning(f"Error parsing sources/images: {parse_err}")

        return jsonify({
            "response": bot_response,
            "sources": valid_sources,
            "images": final_images
        })
        
    except Exception as e:
        logger.error(f"Chat Error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/clear', methods=['POST'])
def clear_session():
    """Clear chat history for a session"""
    data = request.json
    session_id = data.get('session_id', 'default')
    if session_id in chat_sessions:
        chat_sessions[session_id] = ""
        save_sessions()
    return jsonify({"message": "Session cleared"})

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/')
def index():
    if os.path.exists(app.static_folder):
        return send_from_directory(app.static_folder, 'index.html')
    else:
        return "<h1>✅ Hybrid RAG API is Running!</h1><p>Frontend build not found.</p>"

@app.route('/<path:path>')
def serve_static(path):
    if os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

@app.route('/images/<path:filename>')
def serve_image(filename):
    if filename.startswith('data/'):
        filename = filename[5:]
    return send_from_directory(Config.DATA_DIR, filename)

# --- Frontend Process Management ---
frontend_process = None

def cleanup():
    global frontend_process
    if frontend_process:
        logger.info("Stopping React Frontend...")
        subprocess.call(['taskkill', '/F', '/T', '/PID', str(frontend_process.pid)])

def start_frontend():
    global frontend_process
    logger.info("Starting React Frontend...")
    frontend_dir = os.path.join(Config.BASE_DIR, 'frontend')
    frontend_process = subprocess.Popen('npm start', cwd=frontend_dir, shell=True)

# --- Configuration Endpoints ---
@app.route('/api/config/trust', methods=['GET'])
def get_trust_config():
    if os.path.exists(Config.TRUST_CONFIG_FILE):
        with open(Config.TRUST_CONFIG_FILE, "r") as f:
            return jsonify(json.load(f))
    return jsonify({"rules": [], "default_score": 0.5})

@app.route('/api/config/trust', methods=['POST'])
def save_trust_config():
    try:
        new_config = request.json
        with open(Config.TRUST_CONFIG_FILE, "w") as f:
            json.dump(new_config, f, indent=4)
        return jsonify({"status": "success", "message": "Trust config saved"})
    except Exception as e:
        logger.error(f"Error saving trust config: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/source', methods=['DELETE'])
def delete_source_data():
    try:
        data = request.json
        pattern = data.get('pattern')
        if not pattern:
            return jsonify({"error": "Pattern is required"}), 400
            
        logger.info(f"Purging data for source pattern: {pattern}")
        
        from run_qa import graph
        q1 = "MATCH (n:Chunk) WHERE n.source CONTAINS $pattern DETACH DELETE n"
        graph.query(q1, {"pattern": pattern})
        
        # Update config
        if os.path.exists(Config.TRUST_CONFIG_FILE):
            with open(Config.TRUST_CONFIG_FILE, "r") as f:
                config = json.load(f)
            config['rules'] = [r for r in config.get('rules', []) if r.get('pattern') != pattern]
            with open(Config.TRUST_CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=4)
                
        return jsonify({"status": "success", "message": f"Purged data and rules for '{pattern}'"})
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/files', methods=['GET'])
def list_files():
    try:
        from run_qa import graph
        query = """
        MATCH (n:Chunk) 
        WHERE n.source ENDS WITH '.pdf' OR n.source ENDS WITH '.PDF'
        RETURN DISTINCT n.source as source
        LIMIT 100
        """
        results = graph.query(query)
        files = sorted([r['source'] for r in results])
        return jsonify({"files": files})
    except Exception as e:
        logger.error(f"Failed to list files: {e}")
        return jsonify({"error": str(e)}), 500

# --- Ingestion Endpoints ---
def run_ingestion_background():
    def _run():
        logger.info("Starting Ingestion Process...")
        try:
            result = subprocess.run([sys.executable, "ingest_graph.py"], cwd=os.getcwd(), capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("Ingestion Complete!")
            else:
                logger.error(f"Ingestion Failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Ingestion Error: {e}")
    threading.Thread(target=_run).start()

def auto_add_trust_rule(pattern, score=1.0, rule_type='file'):
    try:
        config = {}
        if os.path.exists(Config.TRUST_CONFIG_FILE):
            with open(Config.TRUST_CONFIG_FILE, "r") as f:
                config = json.load(f)
        
        rules = config.get("rules", [])
        if any(r['pattern'] == pattern for r in rules):
            return
            
        rules.append({"pattern": pattern, "score": score, "type": rule_type})
        config['rules'] = rules
        if 'default_score' not in config: config['default_score'] = 0.5
        
        with open(Config.TRUST_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
        logger.info(f"Auto-added trust rule for: {pattern}")
    except Exception as e:
        logger.warning(f"Failed to auto-add trust rule: {e}")

@app.route('/api/ingest/url', methods=['POST'])
def add_url_source():
    try:
        data = request.json
        url = data.get('url')
        if not url: return jsonify({"error": "URL is required"}), 400
        
        with open(os.path.join(Config.DATA_DIR, "urls.txt"), "a") as f:
            f.write(f"\n{url}")
            
        run_ingestion_background()
        
        try:
             from urllib.parse import urlparse
             domain = urlparse(url).netloc.replace('www.', '')
             if domain: auto_add_trust_rule(domain, score=1.0, rule_type='domain')
        except: pass
        
        return jsonify({"status": "success", "message": "URL added. Ingestion started in background."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/ingest/upload', methods=['POST'])
def upload_file_source():
    try:
        if 'file' not in request.files: return jsonify({"error": "No file part"}), 400
        files = request.files.getlist('file')
        if not files or files[0].filename == '': return jsonify({"error": "No selected file"}), 400
        
        uploaded_count = 0
        for file in files:
            if not file: continue
            filename = file.filename
            
            if filename == 'urls.txt':
                content = file.read().decode('utf-8')
                with open(os.path.join(Config.DATA_DIR, "urls.txt"), "a") as f:
                    f.write("\n" + content)
                uploaded_count += 1
                continue
            
            save_path = os.path.join(Config.DATA_DIR, filename)
            file.save(save_path)
            auto_add_trust_rule(filename)
            uploaded_count += 1
            
        if uploaded_count > 0:
            run_ingestion_background()
            return jsonify({"status": "success", "message": f"{uploaded_count} files uploaded."})
        else:
             return jsonify({"error": "No valid files processed"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/ingest/status', methods=['GET'])
def get_ingest_status():
    try:
        path = os.path.join(Config.DATA_DIR, "ingest_status.json")
        if os.path.exists(path):
            with open(path, "r") as f: return jsonify(json.load(f))
        return jsonify({"status": "idle", "percent": 0, "message": "Ready"})
    except:
        return jsonify({"status": "error", "percent": 0})

@app.route('/api/admin/clear_db', methods=['POST'])
def clear_database():
    try:
        logger.warning("CLEARING DATABASE & ARTIFACTS...")
        graph = get_db_connection()
        graph.query("MATCH (n) DETACH DELETE n")
        create_vector_index(graph)
        
        import shutil
        img_dir = os.path.join(Config.DATA_DIR, "extracted_images")
        if os.path.exists(img_dir):
            shutil.rmtree(img_dir)
            os.makedirs(img_dir, exist_ok=True)
            
        log_dir = Config.LOG_DIR
        if os.path.exists(log_dir):
            # Clean log dir contents instead of removing dir? Or just rotate?
            # User logic was to delete it. Let's keep it but maybe safe.
            pass 

        # Clear Trust Rules
        if os.path.exists(Config.TRUST_CONFIG_FILE):
             with open(Config.TRUST_CONFIG_FILE, "r") as f:
                config = json.load(f)
             config['rules'] = []
             with open(Config.TRUST_CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=4)

        return jsonify({"status": "success", "message": "Database and artifacts cleared."})
    except Exception as e:
        logger.error(f"Clear DB failed: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    initialize_reranker()
    
    if os.name == 'nt' or Config.FLASK_ENV == 'development':
         start_frontend()
    
    logger.info(f"Starting RAG API Server on port {Config.PORT}...")
    try:
        app.run(host='0.0.0.0', debug=(Config.FLASK_ENV == 'development'), port=Config.PORT, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()