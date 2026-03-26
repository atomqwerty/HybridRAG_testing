"""
app/api/auth_routes.py — Authentication & User Management API.

Endpoints:
  POST   /api/auth/login            → { token, user }
  GET    /api/auth/me               → current user info (any authenticated user)
  GET    /api/auth/users            → list users (superadmin only)
  POST   /api/auth/users            → create user (superadmin only)
  PUT    /api/auth/users/<id>/role  → change role (superadmin only)
  PUT    /api/auth/users/<id>/password → change password (superadmin only)
  DELETE /api/auth/users/<id>       → delete user (superadmin only)
  GET    /api/auth/audit            → recent audit log (admin, superadmin)
"""

from flask import Blueprint, request, jsonify
from app.auth import require_role, require_auth, generate_token, get_current_user
from app.services.user_service import UserService
from app.services.audit_service import AuditService
from app.logger import setup_logger

api = Blueprint('auth_api', __name__)
logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Login (public)
# ---------------------------------------------------------------------------

@api.route('/auth/login', methods=['POST'])
def login():
    """
    Authenticate and receive a JWT.
    Body: { "username": "...", "password": "..." }
    """
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'username and password are required'}), 400

    user = UserService.authenticate(username, password)
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401

    token = generate_token(user)
    AuditService.log(actor=user['username'], action='login', detail='Successful login')
    return jsonify({'token': token, 'user': user})


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

@api.route('/auth/me', methods=['GET'])
@require_auth
def me():
    """Returns the current authenticated user's profile."""
    return jsonify(get_current_user())


# ---------------------------------------------------------------------------
# User management (superadmin only)
# ---------------------------------------------------------------------------

@api.route('/auth/users', methods=['GET'])
@require_role('superadmin')
def list_users():
    return jsonify({'users': UserService.get_all()})


@api.route('/auth/users', methods=['POST'])
@require_role('superadmin')
def create_user():
    """
    Body: { "username": "...", "password": "...", "role": "user|admin|superadmin" }
    """
    actor = get_current_user()['username']
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'user')

    if not username or not password:
        return jsonify({'error': 'username and password are required'}), 400

    try:
        user = UserService.create(username=username, password=password, role=role)
        AuditService.log(actor=actor, action='create_user',
                         detail=f'Created user "{username}" with role "{role}"')
        return jsonify({'user': user}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 409


@api.route('/auth/users/<user_id>/role', methods=['PUT'])
@require_role('superadmin')
def change_role(user_id):
    """Body: { "role": "user|admin|superadmin" }"""
    actor = get_current_user()['username']
    data = request.json or {}
    new_role = data.get('role', '')

    try:
        target = UserService.get_by_id(user_id)
        old_role = target['role'] if target else '?'
        user = UserService.change_role(user_id, new_role)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        AuditService.log(actor=actor, action='change_role',
                         detail=f'Changed role of "{user["username"]}"',
                         before=old_role, after=new_role)
        return jsonify({'user': user})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api.route('/auth/users/<user_id>/password', methods=['PUT'])
@require_role('superadmin')
def change_password(user_id):
    """Body: { "password": "..." }"""
    actor = get_current_user()['username']
    data = request.json or {}
    new_pw = data.get('password', '')
    if not new_pw:
        return jsonify({'error': 'password is required'}), 400

    ok = UserService.change_password(user_id, new_pw)
    if not ok:
        return jsonify({'error': 'User not found'}), 404

    target = UserService.get_by_id(user_id)
    AuditService.log(actor=actor, action='change_password',
                     detail=f'Changed password for "{target["username"] if target else user_id}"')
    return jsonify({'status': 'ok'})


@api.route('/auth/users/<user_id>', methods=['DELETE'])
@require_role('superadmin')
def delete_user(user_id):
    actor = get_current_user()
    if actor['sub'] == user_id:
        return jsonify({'error': 'Cannot delete yourself'}), 400

    target = UserService.get_by_id(user_id)
    if not target:
        return jsonify({'error': 'User not found'}), 404

    UserService.delete(user_id)
    AuditService.log(actor=actor['username'], action='delete_user',
                     detail=f'Deleted user "{target["username"]}"')
    return jsonify({'status': 'ok'})


# ---------------------------------------------------------------------------
# Audit log (admin+)
# ---------------------------------------------------------------------------

@api.route('/auth/audit', methods=['GET'])
@require_role('admin', 'superadmin')
def get_audit_log():
    limit = int(request.args.get('limit', 100))
    return jsonify({'entries': AuditService.get_recent(limit)})
