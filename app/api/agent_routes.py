"""
Agent Routes — Exposes each specialist agent as a direct API endpoint.

Clients can call agents directly (bypassing the Supervisor) for precise control,
or use /api/agent/chat to go through the Supervisor automatically.

Endpoints:
    POST /api/agent/chat        — Supervisor auto-routes to best agent
    POST /api/agent/image       — Image Agent directly
    POST /api/agent/table       — Table Agent directly
    POST /api/agent/text        — Text Agent directly
    POST /api/agent/classify    — Supervisor classify only (no LLM answer)
"""
from flask import Blueprint, request, jsonify
import logging

api = Blueprint('agent_api', __name__)
logger = logging.getLogger(__name__)


@api.route('/agent/classify', methods=['POST'])
def classify():
    """
    Run Supervisor classification only — returns intent & entity, no agent answer.
    Body: { "message": "Show me the interior of BYD Atto 3" }
    Returns: { "intent": "visual", "query": "...", "entity": "BYD Atto 3" }
    """
    try:
        data = request.json or {}
        message = data.get('message', '')
        if not message:
            return jsonify({"error": "message is required"}), 400

        from app.agents.supervisor import classify as sup_classify
        result = sup_classify(message)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"[Agent API] /classify error: {e}")
        return jsonify({"error": str(e)}), 500


@api.route('/agent/image', methods=['POST'])
def image_agent():
    """
    Call the Image Agent directly.
    Body: { "query": "red interior", "entity": "BYD Atto 3" }
    Returns: { "images": [...], "context": "...", "sources": [...] }
    """
    try:
        data = request.json or {}
        query = data.get('query', '')
        entity = data.get('entity')
        if not query:
            return jsonify({"error": "query is required"}), 400

        from app.agents.image_agent import run
        result = run(query, entity)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"[Agent API] /image error: {e}")
        return jsonify({"error": str(e)}), 500


@api.route('/agent/table', methods=['POST'])
def table_agent():
    """
    Call the Table Agent directly.
    Body: { "query": "Compare battery capacity of Atto 3 and MG ZS EV" }
    Returns: { "result": "| Model | Battery |...", "context": "...", "agent": "table" }
    """
    try:
        data = request.json or {}
        query = data.get('query', '')
        if not query:
            return jsonify({"error": "query is required"}), 400

        from app.agents.table_agent import run
        result = run(query)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"[Agent API] /table error: {e}")
        return jsonify({"error": str(e)}), 500


@api.route('/agent/text', methods=['POST'])
def text_agent():
    """
    Call the Text Agent directly (full hybrid RAG).
    Body: { "query": "How does the warranty work?", "session_id": "default", "temperature": 0.0 }
    Returns: { "result": "...", "context": "...", "images": [...], "sources": [...] }
    """
    try:
        data = request.json or {}
        query = data.get('query', '')
        session_id = data.get('session_id', 'default')
        temperature = float(data.get('temperature', 0.0))
        is_draft = data.get('is_draft', False)
        if not query:
            return jsonify({"error": "query is required"}), 400

        # Get history from ChatService
        from app.services.chat_service import ChatService
        history = ChatService.get_history(session_id)

        from app.agents.text_agent import run
        result = run(query, history=history, temperature=temperature, is_draft=is_draft)

        # Update history
        ChatService.update_history(session_id, query, result.get("result", ""))

        return jsonify(result), 200
    except Exception as e:
        logger.error(f"[Agent API] /text error: {e}")
        return jsonify({"error": str(e)}), 500


@api.route('/agent/chat', methods=['POST'])
def agent_chat():
    """
    Full Supervisor-routed chat — equivalent to /api/chat but returns agent metadata.
    Body: { "message": "...", "session_id": "default", "temperature": 0.0 }
    Returns: { "result": "...", "images": [...], "sources": [...], "agent": "image|table|text" }
    """
    try:
        data = request.json or {}
        message = data.get('message', '')
        session_id = data.get('session_id', 'default')
        temperature = float(data.get('temperature', 0.0))
        is_draft = data.get('is_draft', False)
        if not message:
            return jsonify({"error": "message is required"}), 400

        from app.services.chat_service import ChatService
        result = ChatService.process_message(message, session_id, temperature, is_draft=is_draft)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"[Agent API] /agent/chat error: {e}")
        return jsonify({"error": str(e)}), 500
