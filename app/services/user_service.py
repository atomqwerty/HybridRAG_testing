"""
app/services/user_service.py — User management backed by data/users.json.
"""

import os
import json
import uuid
from datetime import datetime, timezone
from app.config import Config
from app.auth import hash_password, verify_password
from app.logger import setup_logger

logger = setup_logger(__name__)

_DEFAULT_ADMIN = {
    'username': 'admin',
    'password': 'admin',
    'role': 'superadmin',
}

VALID_ROLES = {'user', 'admin', 'superadmin'}


class UserService:

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load() -> list[dict]:
        path = Config.USERS_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            return []
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    @staticmethod
    def _save(users: list[dict]) -> None:
        path = Config.USERS_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(users, f, indent=2)

    @classmethod
    def _ensure_seed(cls) -> None:
        """Create default superadmin if no users exist."""
        users = cls._load()
        if not users:
            logger.info('No users found — seeding default superadmin account (admin/admin).')
            cls.create(
                username=_DEFAULT_ADMIN['username'],
                password=_DEFAULT_ADMIN['password'],
                role=_DEFAULT_ADMIN['role'],
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def get_all(cls) -> list[dict]:
        cls._ensure_seed()
        return [cls._safe(u) for u in cls._load()]

    @classmethod
    def get_by_id(cls, user_id: str) -> dict | None:
        for u in cls._load():
            if u['id'] == user_id:
                return cls._safe(u)
        return None

    @classmethod
    def get_by_username(cls, username: str) -> dict | None:
        """Returns full user record including password_hash (for auth only)."""
        for u in cls._load():
            if u['username'].lower() == username.lower():
                return u
        return None

    @classmethod
    def authenticate(cls, username: str, password: str) -> dict | None:
        """Returns safe user dict if credentials match, else None."""
        cls._ensure_seed()
        user = cls.get_by_username(username)
        if user and verify_password(password, user['password_hash']):
            return cls._safe(user)
        return None

    @classmethod
    def create(cls, username: str, password: str, role: str = 'user') -> dict:
        if role not in VALID_ROLES:
            raise ValueError(f'Invalid role: {role}. Must be one of {VALID_ROLES}')
        users = cls._load()
        if any(u['username'].lower() == username.lower() for u in users):
            raise ValueError(f'Username "{username}" already exists')
        user = {
            'id': str(uuid.uuid4()),
            'username': username,
            'password_hash': hash_password(password),
            'role': role,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        users.append(user)
        cls._save(users)
        logger.info(f'Created user: {username} (role={role})')
        return cls._safe(user)

    @classmethod
    def delete(cls, user_id: str) -> bool:
        users = cls._load()
        before = len(users)
        users = [u for u in users if u['id'] != user_id]
        if len(users) == before:
            return False
        cls._save(users)
        return True

    @classmethod
    def change_role(cls, user_id: str, new_role: str) -> dict | None:
        if new_role not in VALID_ROLES:
            raise ValueError(f'Invalid role: {new_role}')
        users = cls._load()
        for u in users:
            if u['id'] == user_id:
                u['role'] = new_role
                cls._save(users)
                return cls._safe(u)
        return None

    @classmethod
    def change_password(cls, user_id: str, new_password: str) -> bool:
        users = cls._load()
        for u in users:
            if u['id'] == user_id:
                u['password_hash'] = hash_password(new_password)
                cls._save(users)
                return True
        return False

    @staticmethod
    def _safe(user: dict) -> dict:
        """Strip password_hash before returning to caller."""
        return {k: v for k, v in user.items() if k != 'password_hash'}
