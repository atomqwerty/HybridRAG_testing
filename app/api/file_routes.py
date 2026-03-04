from flask import Blueprint, request, jsonify, send_from_directory, current_app
from werkzeug.utils import secure_filename
from app.services.ingest_service import IngestService
from app.services.file_service import FileService
from app.database import get_db_connection
from app.config import Config
from app.utils import update_status
from app.auth import require_role, require_auth, get_current_user
from app.services.audit_service import AuditService
import logging
import os
import json
import threading

api = Blueprint('file_api', __name__)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.txt', '.jpg', '.jpeg', '.png', '.csv', '.xlsx', '.webp'}

@api.route('/ingest/upload', methods=['POST'])
@require_role('admin', 'superadmin')
def upload_file():
    """Uploads files, then starts ingestion in background. Returns 202 immediately."""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400

        files = request.files.getlist('file')
        strategy = request.form.get('strategy', 'dlt')
        # Frontend can send relative paths as a list in 'paths'
        relative_paths = request.form.getlist('paths')

        if not files or all(f.filename == '' for f in files):
            return jsonify({"error": "No files selected"}), 400

        # Save ALL files to disk synchronously BEFORE starting the thread
        saved_paths = []
        for i, file in enumerate(files):
            if file and file.filename:
                # If relative paths provided, preserve structure
                if relative_paths and i < len(relative_paths):
                    rel_path = relative_paths[i]
                    # Secure the whole path except separators
                    # Note: secure_filename only handles base name. 
                    # We need to ensure each component of rel_path is safe.
                    path_parts = [secure_filename(p) for p in rel_path.split('/') if p and p != '..']
                    safe_rel_path = os.path.join(*path_parts)
                    full_dest_path = os.path.join(Config.DATA_DIR, safe_rel_path)
                    os.makedirs(os.path.dirname(full_dest_path), exist_ok=True)
                else:
                    filename = secure_filename(file.filename)
                    full_dest_path = os.path.join(Config.DATA_DIR, filename)

                ext = os.path.splitext(full_dest_path)[1].lower()
                if ext not in ALLOWED_EXTENSIONS:
                    # Cleanup previously saved files if one fails? For now just skip/error
                    return jsonify({"error": f"File type '{ext}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}), 400
                
                file.save(full_dest_path)
                saved_paths.append(full_dest_path)
                logger.info(f"File saved: {full_dest_path}")

        if not saved_paths:
            return jsonify({"error": "No valid files to process"}), 400

        # Write initial status so frontend starts the progress bar immediately
        update_status(f"Preparing to ingest {len(saved_paths)} file(s)...", 5)

        # Run ingestion of ALL files in background thread
        def _ingest():
            try:
                total = len(saved_paths)
                for i, file_path in enumerate(saved_paths):
                    pct = 10 + int((i / total) * 80)  # scale 10→90%
                    update_status(f"Ingesting {os.path.basename(file_path)} ({i+1}/{total})...", pct)
                    IngestService.ingest_document(file_path, strategy=strategy)
                update_status(f"Ingestion Complete ({total} file(s)).", 100)
            except Exception as e:
                logger.error(f"Background ingestion failed: {e}")
                update_status(f"Ingestion failed: {e}", 0, "failed")

        thread = threading.Thread(target=_ingest, daemon=True)
        thread.start()

        actor = get_current_user()
        names = [os.path.basename(p) for p in saved_paths]
        AuditService.log(actor=actor['username'], action='upload_files',
                         detail=f'Uploaded {len(saved_paths)} file(s): {names}')
        return jsonify({"status": "started", "message": f"Ingestion started for {len(saved_paths)} file(s)"}), 202
    except Exception as e:
        logger.error(f"Upload Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/ingest/url', methods=['POST'])
@require_role('admin', 'superadmin')
def ingest_url_sync():
    """Starts URL ingestion in background. Returns 202 immediately."""
    try:
        data = request.json
        if not data or 'url' not in data:
            return jsonify({"error": "URL is required"}), 400

        url = data['url']
        strategy = data.get('strategy', 'dlt')

        # Write initial status so frontend starts the progress bar immediately
        update_status(f"Starting crawl for {url}...", 5)

        # Run ingestion in background thread
        def _ingest():
            try:
                IngestService.ingest_url(url, strategy=strategy)
            except Exception as e:
                logger.error(f"Background URL ingestion failed: {e}")
                update_status(f"Crawl failed: {e}", 0, "failed")

        thread = threading.Thread(target=_ingest, daemon=True)
        thread.start()

        actor = get_current_user()
        AuditService.log(actor=actor['username'], action='crawl_url', detail=f'Started crawl: {url}')
        return jsonify({"status": "started", "message": f"Crawl started for {url}"}), 202
    except Exception as e:
        logger.error(f"Crawl Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/files', methods=['GET'])
@require_auth
def list_files():
    """Lists available files."""
    files = FileService.list_files()
    return jsonify({"files": files})

@api.route('/delete', methods=['POST'])
@require_role('admin', 'superadmin')
def delete_file():
    """Deletes a file."""
    try:
        data = request.json
        filename = data.get('filename')
        result = FileService.delete_file(filename)
        actor = get_current_user()
        AuditService.log(actor=actor['username'], action='delete_file', detail=f'Deleted file: {filename}')
        return jsonify(result)
    except Exception as e:
        logger.error(f"Delete Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/download/<path:filename>', methods=['GET'])
def get_file(filename):
    """Serves raw files."""
    try:
        return send_from_directory(Config.DATA_DIR, filename)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

@api.route('/admin/clear_db', methods=['POST'])
@require_role('superadmin')
def clear_db():
    """Clears database."""
    try:
        result = FileService.clear_database()
        actor = get_current_user()
        AuditService.log(actor=actor['username'], action='clear_db', detail='Cleared entire Neo4j database and files')
        return jsonify(result)
    except Exception as e:
        logger.error(f"Clear DB Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/ingest/status', methods=['GET'])
@require_auth
def get_ingest_status():
    """Returns ingestion status from JSON file."""
    try:
        # Try BASE_DIR first (where update_status() writes), fallback to DATA_DIR
        status_file = os.path.join(Config.BASE_DIR, "ingest_status.json")
        if not os.path.exists(status_file):
            status_file = os.path.join(Config.DATA_DIR, "ingest_status.json")
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                return jsonify(json.load(f))
        return jsonify({"status": "idle", "percent": 0, "message": "No active ingestion."})
    except Exception as e:
        logger.error(f"Status Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/config/trust', methods=['GET'])
def get_trust_config():
    """Returns trust rules configuration."""
    try:
        config_path = Config.TRUST_CONFIG_FILE
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = {"strict_mode": True, "rules": [], "default_score": 0.5}
        else:
            data = {"strict_mode": True, "rules": [], "default_score": 0.5}
        return jsonify(data)
    except Exception as e:
        logger.error(f"Trust Config GET Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/config/trust', methods=['POST'])
@require_role('admin', 'superadmin')
def save_trust_config():
    """Saves trust rules configuration."""
    try:
        data = request.json
        actor = get_current_user()
        with open(Config.TRUST_CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        AuditService.log(actor=actor['username'], action='save_trust_config',
                         detail=f'Saved trust config ({len(data.get("rules", []))} rules)')
        return jsonify({"status": "saved"})
    except Exception as e:
        logger.error(f"Trust Config POST Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/source', methods=['DELETE'])
@require_role('admin', 'superadmin')
def delete_source():
    """Deletes all data from a source pattern from Neo4j."""
    try:
        data = request.json
        pattern = data.get('pattern')
        if not pattern:
            return jsonify({"error": "Pattern required"}), 400

        graph = get_db_connection()
        result = graph.query(
            "MATCH (n) WHERE n.source CONTAINS $pattern OR n.id CONTAINS $pattern "
            "DETACH DELETE n RETURN count(n) as deleted",
            {"pattern": pattern}
        )
        deleted = result[0]["deleted"] if result else 0
        return jsonify({"status": "success", "message": f"Deleted {deleted} nodes matching '{pattern}'"})
    except Exception as e:
        logger.error(f"Source DELETE Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/clear', methods=['POST'])
@require_auth
def clear_chat_history():
    """Clears session chat history."""
    try:
        data = request.json or {}
        session_id = data.get('session_id', 'default')
        # Chat sessions stored in file
        session_file = Config.SESSION_FILE
        if os.path.exists(session_file):
            with open(session_file, 'r') as f:
                sessions = json.load(f)
            if session_id in sessions:
                del sessions[session_id]
                with open(session_file, 'w') as f:
                    json.dump(sessions, f)
        return jsonify({"status": "cleared"})
    except Exception as e:
        logger.error(f"Clear Error: {e}")
        return jsonify({"error": str(e)}), 500

# Endpoint to serve processed images
@api.route('/images/<path:filename>', methods=['GET'])
def get_image(filename):
    try:
        # Check extracted_images subdir first if not absolute
        extracted_path = os.path.join(Config.DATA_DIR, "extracted_images")
        if os.path.exists(os.path.join(extracted_path, filename)):
             return send_from_directory(extracted_path, filename)
        
        # Fallback to data dir root or specific path
        return send_from_directory(Config.DATA_DIR, filename)
    except FileNotFoundError:
        return jsonify({"error": "Image not found"}), 404
