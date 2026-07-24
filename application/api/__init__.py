"""
API
"""
# pylint: disable=line-too-long
from functools import wraps
from datetime import datetime, timedelta
from flask import abort, request, current_app, g
from mongoengine.errors import DoesNotExist, MultipleObjectsReturned
from application.helpers.audit import audit
from application.models.account import Account
from application.models.user import User, find_user_by_api_token
from application import log


# Only refresh a token's last_used stamp at most this often, so a high-rate
# polling client does not trigger a database write on every single request.
_API_TOKEN_TOUCH_INTERVAL = timedelta(seconds=60)


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

def _extract_bearer_token():
    """
    Return a personal API token from the request, or None.

    Accepts ``Authorization: Bearer <token>`` (the standard form) and the
    ``x-login-token`` header for clients that cannot set an Authorization
    header. Basic-auth requests return None here and fall through to the
    username/password path.
    """
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[len('Bearer '):].strip() or None
    return request.headers.get('x-login-token') or None


def _touch_api_token(user, token_obj):
    """
    Stamp ``last_used_at`` on the used token, throttled so busy clients do
    not write on every call. Uses a positional update so it never races
    with a concurrent token change and never rewrites the whole user.
    """
    now = datetime.utcnow()
    if token_obj.last_used_at and now - token_obj.last_used_at < _API_TOKEN_TOUCH_INTERVAL:
        return
    User.objects(id=user.id, api_tokens__token_id=token_obj.token_id).update(
        set__api_tokens__S__last_used_at=now)


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
    # Personal API token (Bearer / x-login-token) takes precedence over the
    # username/password path. A token authenticates as its owner, so it
    # carries exactly the owner's api_roles and api_accounts.
    token = _extract_bearer_token()
    if token:
        if not _is_secure_api_request():
            log.log("API Login failed",
                    details=[('reason', 'HTTPS required'),
                             ('user', 'api-token'),
                             ('ip', request.remote_addr)],
                    source="API")
            abort(401, "HTTPS is required for API authentication")
        user_result, token_obj = find_user_by_api_token(token)
        if not user_result:
            _abort_unauthorized("Invalid or expired API token")
        _touch_api_token(user_result, token_obj)
        return user_result, user_result.name

    username, user_password = _extract_login_credentials()
    if not username:
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
        # Several users match the same login string. Historically this
        # happens when the `name` field (added later, sparse) accidentally
        # matches another account's `email`. We can't drop the branch —
        # purging or unique-indexing the existing duplicates breaks logins
        # for users whose `name` was empty when the field was introduced.
        # So: walk every candidate (constant-time, no early exit) and
        # surface the collision as an audit event so it can be cleaned up.
        candidates = list(User.objects(
            disabled__ne=True,
            __raw__={'$or': [{'name': username}, {'email': username}]}
        ))
        # Constant-time match: check every candidate so a wrong password
        # against the first colliding user takes the same time as the
        # last, which keeps timing from leaking *which* duplicate exists.
        match = None
        for candidate in candidates:
            if candidate.check_password(user_password) and match is None:
                match = candidate
        audit('user.login.collision',
              outcome='success' if match else 'failure',
              actor_type='user',
              actor_id=str(match.id) if match else None,
              actor_name=username,
              metadata={
                  'reason': 'multiple users matched login string',
                  'candidate_count': len(candidates),
                  'candidate_ids': [str(c.id) for c in candidates],
                  'matched_id': str(match.id) if match else None,
              })
        if match is None:
            _abort_unauthorized("Invalid credentials")
        return match, username
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
        g.api_user = user_result
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
            g.api_user = user_result
            roles = user_result.api_roles or []
            if 'all' not in roles and role_name not in roles:
                _abort_unauthorized(
                    f"User '{username}' not allowed for role '{role_name}'"
                )
            return fn(*args, **kwargs)
        return decorated_view
    return decorator


def get_api_account_scope():
    """
    Account-name allowlist for the authenticated API user, or ``None``
    when the user is unrestricted.

    Returns a set of account names the current API user is limited to, or
    ``None`` if the user has no ``api_accounts`` configured (in which case
    every host operation behaves exactly as before). Only meaningful after
    ``require_token`` has run and stored the user on ``flask.g``.
    """
    user = getattr(g, 'api_user', None)
    if user is None:
        return None
    accounts = {name for name in (getattr(user, 'api_accounts', None) or []) if name}
    return accounts or None


def hostnames_in_scope(hostnames, scope):
    """Subset of *hostnames* whose host is inside the account scope.

    ``scope`` is ``None`` (unrestricted → every name passes) or a set of
    allowed account names. Resolves the whole batch in a single query so
    callers never fan out into one lookup per host.
    """
    if scope is None:
        return set(hostnames)
    if not hostnames:
        return set()
    # Imported here to avoid a heavy model import at API-package load time.
    from application.models.host import Host  # pylint: disable=import-outside-toplevel
    allowed = Host.objects(hostname__in=list(hostnames),
                           source_account_name__in=list(scope)).only('hostname')
    return {h.hostname for h in allowed}
