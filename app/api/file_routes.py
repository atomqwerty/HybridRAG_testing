from flask import Blueprint, request, jsonify, send_from_directory, current_app
from app.services.ingest_service import IngestService
from app.services.file_service import FileService
from app.config import Config
import logging
import os

api = Blueprint('file_api', __name__)
logger = logging.getLogger(__name__)

@api.route('/upload', methods=['POST'])
def upload_file():
    """Uploads and ingests a file."""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
            
        file = request.files['file']
        strategy = request.form.get('strategy', 'dlt')
        
        result = FileService.upload_file(file, strategy=strategy)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Upload Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/crawl', methods=['POST'])
def crawl_url():
    """Ingests a URL recursively."""
    try:
        data = request.json
        if not data or 'url' not in data:
            return jsonify({"error": "URL is required"}), 400
            
        url = data['url']
        strategy = data.get('strategy', 'dlt')
        
        # Call IngestService directly (or via FileService if we want to centralize, but direct is fine)
        result = IngestService.ingest_url(url, strategy=strategy)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Crawl Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/files', methods=['GET'])
def list_files():
    """Lists available files."""
    files = FileService.list_files()
    return jsonify({"files": files})

@api.route('/delete', methods=['POST'])
def delete_file():
    """Deletes a file."""
    try:
        data = request.json
        filename = data.get('filename')
        result = FileService.delete_file(filename)
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

@api.route('/clear', methods=['POST'])
def clear_db():
    """Clears database."""
    try:
        result = FileService.clear_database()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Clear DB Error: {e}")
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
