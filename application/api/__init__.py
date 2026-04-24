"""
API
"""
# pylint: disable=line-too-long
from functools import wraps
from flask import abort, request, current_app
from mongoengine.errors import DoesNotExist, MultipleObjectsReturned
from application.models.account import Account
from application.models.user import User
from application import log


def _is_secure_api_request():
    # request.is_secure reflects either a direct TLS connection or the
    # proxy-rewritten scheme when TRUSTED_PROXIES is configured. The raw
    # X-Forwarded-Proto header is intentionally NOT trusted here — a
    # client could set it on an insecure connection and bypass the gate.
    if current_app.config.get("ALLOW_INSECURE_API_AUTH"):
        return True
    if request.is_secure:
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


def _authenticate_user():
    """
    Resolve Basic Auth credentials to an active User, enforcing HTTPS and
    handling historical duplicate names. Returns the User on success or
    aborts with 401. Role checks are the caller's responsibility.
    """
    username, user_password = _extract_login_credentials()
    if not username:
        if request.headers.get('x-login-token'):
            _abort_unauthorized("Invalid or removed login token")
        _abort_unauthorized("No credentials provided")
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
    except DoesNotExist:
        _abort_unauthorized("Invalid credentials")
    except MultipleObjectsReturned:
        user_result = next(
            (candidate for candidate in User.objects(
                disabled__ne=True,
                __raw__={'$or': [{'name': username}, {'email': username}]}
            ) if candidate.check_password(user_password)),
            None,
        )
        if user_result is None:
            _abort_unauthorized("Invalid credentials")
    if not user_result.check_password(user_password):
        _abort_unauthorized("Invalid credentials")
    return user_result, username


def require_token(fn):
    """
    Decorator for Flask-RESTX endpoints mounted under /api/v1. Authenticates
    Basic Auth credentials against a User and grants access when one of the
    user's `api_roles` is ``all`` or a prefix of the request path (so role
    ``syncer`` grants every ``/api/v1/syncer/*`` endpoint, ``ansible`` grants
    ``/api/v1/ansible/*``, and so on).
    """
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        user_result, username = _authenticate_user()
        roles = user_result.api_roles or []
        current_path = request.path.replace('/api/v1/', '')
        allowed = any(
            role == 'all' or current_path.startswith(role)
            for role in roles
        )
        if not allowed:
            _abort_unauthorized(f"User '{username}' not allowed for path '{current_path}'")
        return fn(*args, **kwargs)

    return decorated_view


def require_api_role(role_name):
    """
    Decorator factory for endpoints that live outside ``/api/v1`` (for
    example the Prometheus ``/metrics`` scrape URL). Authenticates Basic
    Auth credentials against a User and grants access when the user's
    ``api_roles`` contains ``all`` or the exact role name given.
    """
    def decorator(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            user_result, username = _authenticate_user()
            roles = user_result.api_roles or []
            if 'all' not in roles and role_name not in roles:
                _abort_unauthorized(
                    f"User '{username}' not allowed for role '{role_name}'"
                )
            return fn(*args, **kwargs)
        return decorated_view
    return decorator
