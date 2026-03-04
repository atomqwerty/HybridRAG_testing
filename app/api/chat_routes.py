from flask import Blueprint, request, jsonify, Response, stream_with_context
from app.services.chat_service import ChatService
import logging

api = Blueprint('chat_api', __name__)
logger = logging.getLogger(__name__)

@api.route('/chat', methods=['POST'])
def chat():
    """
    Standard Chat Endpoint.
    Body: { "message": "...", "session_id": "...", "temperature": 0.0 }
    """
    try:
        data = request.json
        if not data or 'message' not in data:
            return jsonify({"error": "Message is required"}), 400

        message = data.get('message')
        session_id = data.get('session_id', 'default')
        temp = data.get('temperature', 0.0)
        selected_sources = data.get('selected_sources', [])

        response = ChatService.process_message(message, session_id, temp, selected_sources=selected_sources)
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Chat Error: {e}")
        return jsonify({"error": str(e)}), 500

@api.route('/chat/stream', methods=['POST'])
def chat_stream():
    """
    Streaming Chat Endpoint.
    Body: { "message": "...", "session_id": "...", "selected_sources": [] }
    """
    try:
        data = request.json
        message = data.get('message', '') if data else ''
        session_id = data.get('session_id', 'default') if data else 'default'
        temp = data.get('temperature', 0.0) if data else 0.0
        selected_sources = data.get('selected_sources', []) if data else []
        
        if not message:
            return jsonify({"error": "message is required"}), 400
        
        def generate():
            for chunk in ChatService.process_stream(message, session_id, temp, selected_sources=selected_sources):
                yield chunk
                
        return Response(stream_with_context(generate()), mimetype='application/x-ndjson')
        
    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return jsonify({"error": str(e)}), 500
