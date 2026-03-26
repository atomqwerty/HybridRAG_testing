"""
app/services/user_service.py — User management backed by SQLite (SQLAlchemy).
"""

import os
import json
import uuid
from datetime import datetime, timezone
from app.config import Config
from app.auth import hash_password, verify_password
from app.logger import setup_logger
from app.db import get_session, init_db
from app.models import User
from sqlalchemy.exc import IntegrityError

logger = setup_logger(__name__)

_DEFAULT_ADMIN = {
    'username': 'admin',
    'password': 'admin',
    'role': 'superadmin',
}

VALID_ROLES = {'user', 'admin', 'superadmin'}


class UserService:

    @classmethod
    def _migrate_from_json(cls):
        """One-time migration from users.json to SQLite. Runs only if the file exists."""
        path = Config.USERS_FILE
        if not os.path.exists(path):
            return

        logger.info(f"Found legacy users.json at {path}. Migrating to SQLite...")
        try:
            with open(path, 'r') as f:
                legacy_users = json.load(f)

            with get_session() as session:
                for lu in legacy_users:
                    exists = session.query(User).filter_by(username=lu['username']).first()
                    if not exists:
                        session.add(User(
                            id=lu.get('id', str(uuid.uuid4())),
                            username=lu['username'],
                            password_hash=lu['password_hash'],
                            role=lu['role'],
                            created_at=datetime.fromisoformat(lu['created_at'])
                                if 'created_at' in lu else datetime.now(timezone.utc),
                        ))

            # Rename so we never migrate twice
            os.rename(path, path + ".bak")
            logger.info("✅ User migration complete.")
        except Exception as e:
            logger.error(f"Failed to migrate users from JSON: {e}")

    @classmethod
    def _ensure_seed(cls) -> None:
        """Idempotent: create DB tables and seed default superadmin if empty."""
        init_db()
        cls._migrate_from_json()

        with get_session() as session:
            if session.query(User).count() == 0:
                logger.info("No users found — seeding default superadmin (admin/admin).")
                # Call create() outside the session to avoid nesting sessions
                pass  # handled below

        # Check again outside so create() can open its own session
        with get_session() as session:
            if session.query(User).count() == 0:
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
        with get_session() as session:
            return [u.to_dict() for u in session.query(User).all()]

    @classmethod
    def get_by_id(cls, user_id: str) -> dict | None:
        with get_session() as session:
            user = session.get(User, user_id)  # SQLAlchemy 2.0 API
            return user.to_dict() if user else None

    @classmethod
    def get_by_username(cls, username: str) -> dict | None:
        """Returns full record including password_hash (for auth only)."""
        with get_session() as session:
            user = session.query(User).filter(User.username.ilike(username)).first()
            if not user:
                return None
            # Serialize inside session while the object is still attached
            return {
                "id": user.id,
                "username": user.username,
                "password_hash": user.password_hash,
                "role": user.role,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }

    @classmethod
    def authenticate(cls, username: str, password: str) -> dict | None:
        """Returns a safe (no password_hash) user dict on success, else None."""
        cls._ensure_seed()
        user_record = cls.get_by_username(username)
        if user_record and verify_password(password, user_record['password_hash']):
            return {k: v for k, v in user_record.items() if k != 'password_hash'}
        return None

    @classmethod
    def create(cls, username: str, password: str, role: str = 'user') -> dict:
        if role not in VALID_ROLES:
            raise ValueError(f'Invalid role: {role}. Must be one of {VALID_ROLES}')

        new_user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
        )

        try:
            with get_session() as session:
                session.add(new_user)
                session.flush()  # assigns defaults (id, created_at) before commit
                result = new_user.to_dict()  # serialise while still attached
            logger.info(f"Created user: {username} (role={role})")
            return result
        except IntegrityError:
            raise ValueError(f'Username "{username}" already exists')

    @classmethod
    def delete(cls, user_id: str) -> bool:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return False
            session.delete(user)
        return True

    @classmethod
    def change_role(cls, user_id: str, new_role: str) -> dict | None:
        if new_role not in VALID_ROLES:
            raise ValueError(f'Invalid role: {new_role}')

        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return None
            user.role = new_role
            session.flush()
            return user.to_dict()  # serialise while attached

    @classmethod
    def change_password(cls, user_id: str, new_password: str) -> bool:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return False
            user.password_hash = hash_password(new_password)
        return True
