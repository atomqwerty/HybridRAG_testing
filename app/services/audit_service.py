"""
app/services/audit_service.py — Append-only audit trail.

Every admin write action should call:
    AuditService.log(actor, action, detail, before=None, after=None)
"""

import os
import json
from datetime import datetime, timezone
from app.config import Config
from app.logger import setup_logger

logger = setup_logger(__name__)


class AuditService:

    @staticmethod
    def _load() -> list[dict]:
        path = Config.AUDIT_LOG_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            return []
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    @classmethod
    def log(
        cls,
        actor: str,
        action: str,
        detail: str = '',
        before=None,
        after=None,
    ) -> None:
        """
        Append an audit entry.

        Args:
            actor:  Username of the user performing the action.
            action: Short action name, e.g. 'delete_file', 'change_role'.
            detail: Human-readable description, e.g. 'Deleted report.pdf'.
            before: Previous value (for change tracking).
            after:  New value (for change tracking).
        """
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'actor': actor,
            'action': action,
            'detail': detail,
        }
        if before is not None:
            entry['before'] = before
        if after is not None:
            entry['after'] = after

        try:
            records = cls._load()
            records.append(entry)
            with open(Config.AUDIT_LOG_FILE, 'w') as f:
                json.dump(records, f, indent=2)
            logger.info(f'[AUDIT] {actor} → {action}: {detail}')
        except Exception as e:
            logger.error(f'Failed to write audit log: {e}')

    @classmethod
    def get_recent(cls, limit: int = 100) -> list[dict]:
        """Returns the most recent `limit` audit entries (newest first)."""
        records = cls._load()
        return list(reversed(records[-limit:]))
