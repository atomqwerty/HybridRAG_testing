"""
app/auth.py — JWT Authentication & RBAC decorators.

Usage:
    from app.auth import require_role, get_current_user

    @api.route('/admin/something')
    @require_role('admin', 'superadmin')
    def admin_endpoint():
        user = get_current_user()
        ...
"""

import jwt
import bcrypt
import datetime
from functools import wraps
from flask import request, jsonify, g
from app.config import Config
from app.logger import setup_logger

logger = setup_logger(__name__)

# Role hierarchy (higher index = more permissions)
ROLE_HIERARCHY = ['user', 'admin', 'superadmin']


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def generate_token(user: dict) -> str:
    """Generate a signed JWT for the user dict (must have id, username, role)."""
    payload = {
        'sub': user['id'],
        'username': user['username'],
        'role': user['role'],
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=Config.TOKEN_EXPIRY_HOURS),
        'iat': datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])


def get_current_user() -> dict | None:
    """Returns the decoded token payload from flask.g (set by require_role)."""
    return getattr(g, 'current_user', None)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def _extract_token() -> str | None:
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    return None


def require_role(*allowed_roles: str):
    """
    Flask route decorator that enforces authentication and role membership.

    Example:
        @require_role('admin', 'superadmin')
        def my_admin_view(): ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = _extract_token()
            if not token:
                return jsonify({'error': 'Authentication required'}), 401

            try:
                payload = decode_token(token)
            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except jwt.PyJWTError as e:
                return jsonify({'error': f'Invalid token: {e}'}), 401

            user_role = payload.get('role', 'user')
            if user_role not in allowed_roles:
                return jsonify({'error': f'Requires role: {", ".join(allowed_roles)}'}), 403

            g.current_user = payload
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_auth(fn):
    """Decorator that only checks authentication (any valid role allowed)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        if not token:
            return jsonify({'error': 'Authentication required'}), 401
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.PyJWTError as e:
            return jsonify({'error': f'Invalid token: {e}'}), 401
        g.current_user = payload
        return fn(*args, **kwargs)
    return wrapper
