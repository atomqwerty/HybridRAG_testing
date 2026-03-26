from flask import Blueprint, request, jsonify
from app.auth import require_auth, require_role, get_current_user
from app.db import get_session, init_db
from app.models import RagConfig
from app.services.audit_service import AuditService
import logging

api = Blueprint('config_api', __name__)
logger = logging.getLogger(__name__)


def _get_or_create_rag_config(session, config_id="1"):
    """Returns the singleton RagConfig row (1=Live, 2=Draft), creating it with defaults if absent."""
    cfg = session.query(RagConfig).filter(RagConfig.id == config_id).first()
    if not cfg:
        cfg = RagConfig(id=config_id)
        if config_id == "2":
            # Seed draft from live if it exists
            live = session.query(RagConfig).filter(RagConfig.id == "1").first()
            if live:
                cfg.k = live.k
                cfg.k_keyword = live.k_keyword
                cfg.min_score = live.min_score
                cfg.top_k_rerank = live.top_k_rerank
                cfg.multi_query = live.multi_query
                cfg.system_prompt = live.system_prompt
                cfg.persona_name = live.persona_name
        session.add(cfg)
        session.flush()
    return cfg


@api.route('/config/rag', methods=['GET'])
@require_auth
def get_rag_config():
    """Returns the requested RAG tuning parameters (default to live)."""
    init_db()
    config_id = request.args.get('id', '1') # 1=Live, 2=Draft
    with get_session() as session:
        cfg = _get_or_create_rag_config(session, config_id)
        return jsonify(cfg.to_dict())


@api.route('/config/rag', methods=['PATCH'])
@require_role('admin', 'superadmin')
def update_rag_config():
    """
    Updates RAG tuning parameters.
    Accepted fields: k, k_keyword, min_score, top_k_rerank, multi_query
    """
    init_db()
    user = get_current_user()
    data = request.json or {}

    allowed = {'k', 'k_keyword', 'min_score', 'top_k_rerank', 'multi_query'}
    changes = {k: v for k, v in data.items() if k in allowed}
    if not changes:
        return jsonify({"error": "No valid fields provided"}), 400

    with get_session() as session:
        # Changes always applied to Draft (ID=2)
        cfg = _get_or_create_rag_config(session, "2")
        before = cfg.to_dict()

        for field, val in changes.items():
            if field == 'multi_query':
                setattr(cfg, field, "true" if val else "false")
            elif field in ('system_prompt', 'persona_name'):
                setattr(cfg, field, str(val))
            elif field == 'min_score':
                setattr(cfg, field, str(round(float(val), 4)))
            else:
                setattr(cfg, field, str(int(val)))

        cfg.updated_by = user.get('username') or user.get('sub', 'unknown')
        after = cfg.to_dict()

    # Audit the change
    try:
        AuditService.log(
            actor=cfg.updated_by,
            action="UPDATE_RAG_CONFIG",
            detail="RAG retrieval parameters updated",
            before=before,
            after=after,
        )
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")

    return jsonify({"status": "updated", "config": after})


@api.route('/config/rag/publish', methods=['POST'])
@require_role('admin', 'superadmin')
def publish_rag_config():
    """Promotes Draft (ID=2) to Live (ID=1)."""
    init_db()
    user = get_current_user()
    
    with get_session() as session:
        draft = _get_or_create_rag_config(session, "2")
        live = _get_or_create_rag_config(session, "1")
        
        before = live.to_dict()
        
        # Copy fields
        live.k = draft.k
        live.k_keyword = draft.k_keyword
        live.min_score = draft.min_score
        live.top_k_rerank = draft.top_k_rerank
        live.multi_query = draft.multi_query
        live.system_prompt = draft.system_prompt
        live.persona_name = draft.persona_name
        live.updated_by = user.get('username') or user.get('sub', 'unknown')
        
        after = live.to_dict()

    # Audit the change
    try:
        AuditService.log(
            actor=live.updated_by,
            action="PUBLISH_RAG_CONFIG",
            detail="Draft RAG settings published to production",
            before=before,
            after=after,
        )
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")

    return jsonify({"status": "published", "config": after})
