"""
API
"""
from functools import wraps
from flask import abort, request, current_app
from application.models.account import Account
from application.models.user import User
from mongoengine.errors import DoesNotExist


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

def require_token(fn): #pylint: disable=invalid-name
    """
    Decorator for Endpoints with token
    """
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        username, user_password = _extract_login_credentials()
        if username:
            if not _is_secure_api_request():
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
                        abort(401, "Not sufficent rights")
            except DoesNotExist:
                abort(401, "Invalid login")
            if not user_result.check_password(user_password):
                abort(401, "Invalid login")
        elif request.headers.get('x-login-token'):
            abort(
                401,
                "Please Migrate to x-login-user authentication. "
                "Due to security reasons, this login is no longer possible"
            )
        else:
            abort(401, "Invalid Request, Loginheader missing")

        return fn(*args, **kwargs)

    return decorated_view
