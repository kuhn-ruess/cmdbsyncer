"""
API
"""
from functools import wraps
from flask import abort, request, current_app
from mongoengine.errors import DoesNotExist
from application.models.account import Account
from application.models.user import User
from application import log


def _is_secure_api_request():
    if current_app.config.get("ALLOW_INSECURE_API_AUTH"):
        return True
    if request.is_secure:
        return True
    if request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        return True
    if request.host.split(":", 1)[0].lower() == "localhost":
        return True
    return request.remote_addr in {"127.0.0.1", "::1"}


def _extract_login_credentials():
    auth = request.authorization
    if auth and auth.username and auth.password is not None:
        return auth.username, auth.password

    login_user = request.headers.get('x-login-user')
    if login_user:
        if ':' not in login_user:
            abort(401, "Invalid login")
        return login_user.split(':', 1)
    return None, None

def _abort_unauthorized(reason="Unauthorized"):
    details = [
        ('reason', reason),
        ('user', f"{request.authorization.username if request.authorization else 'unknown'}"),
        ('ip', request.remote_addr),
    ]
    log.log("API Login failed",
            details=details,
            source="API")
    abort(401, "unauthorized")


def require_token(fn):
    """
    Decorator for Endpoints with token
    """
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        username, user_password = _extract_login_credentials()
        if username:
            if not _is_secure_api_request():
                details = [
                    ('reason', 'HTTPS required'),
                    ('user', username),
                    ('ip', request.remote_addr),
                ]
                log.log("API Login failed", details=details, source="API")
                abort(401, "HTTPS is required for password-based API authentication")
            try:
                user_result = User.objects.get(
                    disabled__ne=True,
                    __raw__={'$or': [{'name': username}, {'email': username}]}
                )
                roles = user_result.api_roles
                current_path = request.path.replace('/api/v1/','')
                if roles:
                    allowed = False
                    for role in roles:
                        if role == 'all':
                            allowed = True
                            break
                        if current_path.startswith(role):
                            allowed = True
                    if not allowed:
                        _abort_unauthorized(f"User '{username}' not allowed for path '{current_path}'")
            except DoesNotExist:
                _abort_unauthorized(f"User '{username}' not found")
            if not user_result.check_password(user_password):
                _abort_unauthorized(f"Wrong password for user '{username}'")
        elif request.headers.get('x-login-token'):
            _abort_unauthorized("Invalid or removed login token")
        else:
            _abort_unauthorized("No credentials provided")

        return fn(*args, **kwargs)

    return decorated_view
