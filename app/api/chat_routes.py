from flask import Blueprint, request, jsonify, Response, stream_with_context
from app.services.chat_service import ChatService
from app.auth import require_auth, get_current_user
from app.db import get_session, init_db
from app.models import ChatMessage
from sqlalchemy import func, distinct
import logging

api = Blueprint('chat_api', __name__)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Standard / streaming chat
# ---------------------------------------------------------------------------

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
        is_draft = data.get('is_draft', False)

        response = ChatService.process_message(message, session_id, temp, selected_sources=selected_sources, is_draft=is_draft)
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
        is_draft = data.get('is_draft', False) if data else False

        if not message:
            return jsonify({"error": "message is required"}), 400

        def generate():
            for chunk in ChatService.process_stream(message, session_id, temp, selected_sources=selected_sources, is_draft=is_draft):
                yield chunk

        return Response(stream_with_context(generate()), mimetype='application/x-ndjson')

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Chat Sessions
# ---------------------------------------------------------------------------

@api.route('/chat/sessions', methods=['GET'])
@require_auth
def list_sessions():
    """
    Returns a list of chat sessions for the current user.
    Each session includes: session_id, title (first user message), last_at.
    """
    init_db()
    user = get_current_user()
    user_id = user['sub']

    with get_session() as session:
        # Get all messages ordered oldest first so we can grab the first user msg per session
        msgs = (
            session.query(ChatMessage)
            .filter(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.timestamp.asc())
            .all()
        )

        sessions_map = {}
        for msg in msgs:
            sid = msg.session_id
            if sid not in sessions_map:
                sessions_map[sid] = {
                    "session_id": sid,
                    "title": None,
                    "last_at": msg.timestamp.isoformat() if msg.timestamp else None,
                }
            # Use the first user message as the title
            if sessions_map[sid]["title"] is None and msg.role == "user":
                title = msg.content[:60]
                sessions_map[sid]["title"] = title + ("…" if len(msg.content) > 60 else "")
            # Always keep the most recent timestamp
            if msg.timestamp:
                sessions_map[sid]["last_at"] = msg.timestamp.isoformat()

        # Sort most recent first
        result = sorted(sessions_map.values(), key=lambda x: x["last_at"] or "", reverse=True)

        return jsonify({"sessions": result})


# ---------------------------------------------------------------------------
# Chat History
# ---------------------------------------------------------------------------

@api.route('/chat/history', methods=['GET'])
@require_auth
def get_history():
    """
    Returns the current user's chat messages.
    Optional ?session_id=<id> to filter to a specific thread.
    """
    init_db()
    user = get_current_user()
    user_id = user['sub']
    limit = int(request.args.get('limit', 200))
    session_id = request.args.get('session_id', None)

    with get_session() as session:
        query = (
            session.query(ChatMessage)
            .filter(ChatMessage.user_id == user_id)
        )
        if session_id:
            query = query.filter(ChatMessage.session_id == session_id)
        msgs = query.order_by(ChatMessage.timestamp.asc()).limit(limit).all()
        return jsonify({"messages": [m.to_dict() for m in msgs]})


@api.route('/chat/history', methods=['POST'])
@require_auth
def save_messages():
    """
    Saves one or more messages for the current user.
    Body: {
        "session_id": "...",
        "messages": [
            { "role": "user"|"bot", "content": "...", "sources": [...] },
            ...
        ]
    }
    """
    init_db()
    user = get_current_user()
    user_id = user['sub']
    data = request.json or {}
    session_id = data.get('session_id', 'default')
    messages = data.get('messages', [])

    if not messages:
        return jsonify({"error": "messages list is required"}), 400

    with get_session() as db_session:
        for m in messages:
            role = m.get('role', 'user')
            content = m.get('content', '')
            sources = m.get('sources', [])
            if not content:
                continue
            db_session.add(ChatMessage(
                user_id=user_id,
                session_id=session_id,
                role=role,
                content=content,
                sources=sources,
            ))

    return jsonify({"status": "saved", "count": len(messages)}), 201


@api.route('/chat/history', methods=['DELETE'])
@require_auth
def clear_history():
    """
    Deletes chat history for the current user.
    Optional ?session_id=<id> to delete only one thread.
    """
    init_db()
    user = get_current_user()
    user_id = user['sub']
    session_id = request.args.get('session_id', None)

    with get_session() as db_session:
        query = db_session.query(ChatMessage).filter(ChatMessage.user_id == user_id)
        if session_id:
            query = query.filter(ChatMessage.session_id == session_id)
        deleted = query.delete()

    logger.info(f"Cleared {deleted} messages for user {user_id}")
    return jsonify({"status": "cleared", "deleted": deleted})
