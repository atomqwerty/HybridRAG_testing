"""
app/services/audit_service.py — Append-only audit trail backed by SQLite.

Every admin write action should call:
    AuditService.log(actor, action, detail, before=None, after=None)
"""

import os
import json
from datetime import datetime, timezone
from app.config import Config
from app.logger import setup_logger
from app.db import get_session, init_db
from app.models import AuditLog

logger = setup_logger(__name__)


class AuditService:

    @classmethod
    def _migrate_from_json(cls):
        """One-time migration from audit_log.json to SQLite. Runs only if the file exists."""
        path = Config.AUDIT_LOG_FILE
        if not os.path.exists(path):
            return

        logger.info(f"Found legacy audit_log.json at {path}. Migrating to SQLite...")
        try:
            with open(path, 'r') as f:
                legacy_logs = json.load(f)

            with get_session() as session:
                for ll in legacy_logs:
                    session.add(AuditLog(
                        timestamp=datetime.fromisoformat(ll['timestamp'])
                            if 'timestamp' in ll else datetime.now(timezone.utc),
                        actor=ll['actor'],
                        action=ll['action'],
                        detail=ll.get('detail', ''),
                        before=ll.get('before'),
                        after=ll.get('after'),
                    ))

            os.rename(path, path + ".bak")
            logger.info("✅ Audit log migration complete.")
        except Exception as e:
            logger.error(f"Failed to migrate audit logs from JSON: {e}")

    @classmethod
    def log(
        cls,
        actor: str,
        action: str,
        detail: str = '',
        before=None,
        after=None,
    ) -> None:
        """Append an immutable audit entry to the database."""
        # Tables must exist before writing
        init_db()

        try:
            with get_session() as session:
                session.add(AuditLog(
                    actor=actor,
                    action=action,
                    detail=detail,
                    before=before,
                    after=after,
                ))
            logger.info(f"[AUDIT] {actor} → {action}: {detail}")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    @classmethod
    def get_recent(cls, limit: int = 100) -> list[dict]:
        """Returns the most recent `limit` audit entries (newest first)."""
        init_db()
        cls._migrate_from_json()

        with get_session() as session:
            logs = (
                session.query(AuditLog)
                .order_by(AuditLog.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [l.to_dict() for l in logs]
