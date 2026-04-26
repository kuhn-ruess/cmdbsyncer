"""Entry point for the ``cmdbsyncer-mcp`` console script.

Exposes the syncer over the Model Context Protocol (MCP) so Claude
Desktop, Cursor, Cline and other MCP clients can read and write syncer
state. Boots in CLI mode (no Flask-Admin, no REST blueprints) so cold
start stays under ~250 ms.

Authentication
--------------
Same model as the REST API: a syncer ``User`` with the ``mcp`` (or
``all``) ``api_role`` authenticates via HTTP Basic. A user without that
role is rejected at the boundary, so per-tool role checks are not
needed inside the tool bodies.

stdio transport
    Credentials are passed at startup via ``--user``/``--password`` or
    ``CMDBSYNCER_API_USER`` / ``CMDBSYNCER_API_PASSWORD`` env vars.
    The parent process owns the pipe — there is nobody else to
    authenticate.

sse / HTTP transport
    Credentials are checked **per request** by a Starlette middleware.
    Every connection presents ``Authorization: Basic …``; the
    resolved User is bound to a per-request contextvar. HTTPS is
    required (mirrors ``application.api.require_token``); plain HTTP
    is only allowed from localhost or with
    ``ALLOW_INSECURE_API_AUTH=True`` in ``local_config.py``. This
    way an open port does *not* equal full access — every tool call
    re-validates the caller.
"""
import argparse
import base64
import contextvars
import json
import os
import sys

# Mark the process as CLI before importing ``application``: that gates
# the Flask-Admin, blueprint and view registrations out of the boot path.
os.environ['CMDBSYNCER_CLI'] = '1'
os.environ.setdefault('config', 'prod')


def _abort(message, code=1):
    """Print to stderr and exit. stdout is the MCP transport — never write there."""
    print(message, file=sys.stderr)
    sys.exit(code)


try:
    from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error
except ImportError:
    _abort(
        "MCP SDK not installed. Run:\n"
        "  pip install -r requirements-extras.txt\n"
        "or\n"
        "  pip install 'mcp>=1.10'"
    )


# pylint: disable=wrong-import-position
from datetime import datetime, timedelta

from mongoengine.errors import DoesNotExist, MultipleObjectsReturned

import application  # pylint: disable=unused-import  # noqa: F401 — boot side effect
from application import app
from application.models.user import User
from application.models.host import Host
from application.models.account import Account
from application.models.cron import CronStats, CronGroup
from application.modules.log.models import LogEntry
from application.helpers.get_account import (
    get_account_by_name,
    AccountNotFoundError,
)
from application.plugins.rules.rule_definitions import rules as enabled_rules
from application.plugins.rules.rule_import_export import (
    iter_rules_of_type,
    import_one_rule,
    import_json_bundle,
    grouped_rules_export,
)
from application.plugins.rules.autorules import create_rules
from application.plugins.checkmk.models import CheckmkFolderPool


# ---------------------------------------------------------------------------
# Auth — stdio binds a single user at startup; sse binds per-request.
# ---------------------------------------------------------------------------


_AUTH_USER = None  # stdio mode only
_request_user: contextvars.ContextVar = contextvars.ContextVar(
    'cmdbsyncer_mcp_user', default=None,
)


class MCPAuthError(Exception):
    """Raised when no authenticated User is bound for the current call."""


def _user_has_mcp_access(user):
    """``mcp`` (or ``all``) in api_roles is the umbrella grant for the
    server. Per-tool role checks are intentionally *not* layered on top —
    the role explicitly opts a user in to MCP."""
    roles = user.api_roles or []
    return 'all' in roles or 'mcp' in roles


def _resolve_user(name, password):
    """Look up an enabled User by name/email + password. Returns the User
    on success or ``None`` on any failure (no logging, no abort)."""
    try:
        candidate = User.objects.get(
            disabled__ne=True,
            __raw__={'$or': [{'name': name}, {'email': name}]},
        )
    except DoesNotExist:
        return None
    except MultipleObjectsReturned:
        # Historical duplicate names: pick the first that authenticates.
        candidate = next(
            (c for c in User.objects(
                disabled__ne=True,
                __raw__={'$or': [{'name': name}, {'email': name}]},
            ) if c.check_password(password)),
            None,
        )
        if candidate is None:
            return None
    if not candidate.check_password(password):
        return None
    return candidate


def _login_stdio(username, password):
    """stdio mode startup login. Aborts on failure or missing role."""
    global _AUTH_USER  # pylint: disable=global-statement
    user = _resolve_user(username, password)
    if user is None:
        _abort(f"Authentication failed for user '{username}'")
    if not _user_has_mcp_access(user):
        _abort(
            f"User '{username}' has no 'mcp' or 'all' api_role. Grant the "
            f"role from Profile → Users in the admin UI."
        )
    _AUTH_USER = user


def _current_user():
    """Return the User bound to this MCP call (SSE per-request, stdio global)."""
    user = _request_user.get() or _AUTH_USER
    if user is None:
        raise MCPAuthError("Not authenticated")
    return user


# ---------------------------------------------------------------------------
# Helpers shared with the REST API
# ---------------------------------------------------------------------------


def _serialize(value):
    """Recursively convert datetimes to ISO-8601 UTC strings for JSON output."""
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%dT%H:%M:%SZ')
    return value


def _host_to_dict(host_obj):
    return {
        'hostname': host_obj.hostname,
        'labels': _serialize(host_obj.get_labels()),
        'inventory': _serialize(host_obj.get_inventory()),
        'last_seen': (host_obj.last_import_seen.strftime('%Y-%m-%dT%H:%M:%SZ')
                      if host_obj.last_import_seen else None),
        'last_update': (host_obj.last_import_sync.strftime('%Y-%m-%dT%H:%M:%SZ')
                        if host_obj.last_import_sync else None),
    }


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------


mcp = FastMCP("cmdbsyncer")


# --- Hosts / objects --------------------------------------------------------


@mcp.tool()
def list_hosts(start: int = 0, limit: int = 100) -> dict:
    """List host objects with cursor-style pagination.

    Returns ``{results, start, limit, size}`` where ``results`` is a list
    of ``{hostname, labels, inventory, last_seen, last_update}`` dicts.
    Excludes non-host objects (``is_object=True``).
    """
    _current_user()
    if start < 0 or limit < 0:
        raise ValueError("start and limit must be non-negative")
    queryset = Host.objects(is_object__ne=True)
    total = queryset.count()
    end = start + limit
    return {
        'results': [_host_to_dict(h) for h in queryset[start:end]],
        'start': start,
        'limit': limit,
        'size': total,
    }


@mcp.tool()
def get_host(hostname: str) -> dict:
    """Return labels, inventory and timestamps for *hostname*."""
    _current_user()
    try:
        host = Host.objects.get(hostname=hostname)
    except DoesNotExist as exc:
        raise ValueError(f"Host '{hostname}' not found") from exc
    return _host_to_dict(host)


@mcp.tool()
def upsert_host(hostname: str, account: str, labels: dict) -> dict:
    """Create or update a host, binding it to *account*.

    Hosts already bound to a different account are not re-bound — the
    call returns ``{"status": "account_conflict"}`` instead. To re-bind
    a host, edit it from the admin UI.
    """
    _current_user()
    try:
        account_dict = get_account_by_name(account)
    except AccountNotFoundError as exc:
        raise ValueError(f"Account '{account}' not found") from exc
    host_obj = Host.get_host(hostname)
    try:
        host_obj.update_host(labels)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not host_obj.set_account(account_dict=account_dict):
        return {'status': 'account_conflict', 'hostname': hostname}
    host_obj.save()
    return {'status': 'saved', 'hostname': hostname}


@mcp.tool()
def delete_host(hostname: str) -> dict:
    """Delete *hostname*. Frees a Checkmk folder pool seat if held."""
    _current_user()
    host_obj = Host.get_host(hostname, create=False)
    if not host_obj:
        return {'status': 'not_found', 'hostname': hostname}
    folder = host_obj.folder
    if folder:
        try:
            pool = CheckmkFolderPool.objects.get(folder_name__iexact=folder)
        except DoesNotExist:
            pool = None
        if pool and pool.folder_seats_taken > 0:
            pool.folder_seats_taken -= 1
            pool.save()
    host_obj.delete()
    return {'status': 'deleted', 'hostname': hostname}


@mcp.tool()
def update_host_inventory(hostname: str, key: str, inventory: dict) -> dict:
    """Replace the inventory section identified by *key* on *hostname*.

    Inventory writes never auto-create a host — *hostname* must already
    exist (use ``upsert_host`` first).
    """
    _current_user()
    host_obj = Host.get_host(hostname, create=False)
    if not host_obj:
        return {'status': 'not_found', 'hostname': hostname}
    try:
        host_obj.update_inventory(key, inventory)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    host_obj.save()
    return {'status': 'saved', 'hostname': hostname, 'key': key}


# --- Accounts ---------------------------------------------------------------


@mcp.tool()
def list_accounts() -> dict:
    """List all accounts with name, type and enabled flag."""
    _current_user()
    out = []
    for acc in Account.objects.only('name', 'type', 'enabled', 'is_master',
                                    'is_child'):
        out.append({
            'name': acc.name,
            'type': acc.type,
            'enabled': acc.enabled,
            'is_master': acc.is_master,
            'is_child': acc.is_child,
        })
    return {'accounts': out}


@mcp.tool()
def get_account(name: str) -> dict:
    """Return the resolved account record (custom_fields flattened, child
    inheriting from parent). Includes the cleartext password — handle with
    care; only callers with the ``mcp`` (or ``all``) api_role can call."""
    _current_user()
    try:
        return _serialize(get_account_by_name(name))
    except AccountNotFoundError as exc:
        raise ValueError(f"Account '{name}' not found") from exc


# --- Rules ------------------------------------------------------------------


@mcp.tool()
def list_rule_types() -> dict:
    """Return the supported ``rule_type`` idents."""
    _current_user()
    return {'rule_types': sorted(enabled_rules)}


@mcp.tool()
def export_rules(rule_type: str) -> dict:
    """Export every rule of *rule_type* as a list of dicts."""
    _current_user()
    if rule_type not in enabled_rules:
        raise ValueError(f"Unknown rule_type '{rule_type}'")
    rules = []
    for raw in iter_rules_of_type(rule_type):
        try:
            rules.append(json.loads(raw))
        except (ValueError, TypeError):
            continue
    return {'rule_type': rule_type, 'rules': rules}


@mcp.tool()
def export_all_rules(include_hosts: bool = False,
                     include_accounts: bool = False,
                     include_users: bool = False) -> dict:
    """Export every enabled rule type, grouped by type.

    ``host_objects``, ``accounts`` and ``users`` are skipped by default —
    pass the matching flag to opt in. The user export contains hashed
    passwords; treat the response as secret.
    """
    _current_user()
    return grouped_rules_export(
        include_hosts=include_hosts,
        include_accounts=include_accounts,
        include_users=include_users,
    )


@mcp.tool()
def create_rule(rule_type: str, rule: dict) -> dict:
    """Create one rule of *rule_type*. The dict shape is the same as the
    export form (one ``Document.to_json()`` per rule)."""
    _current_user()
    if rule_type not in enabled_rules:
        raise ValueError(f"Unknown rule_type '{rule_type}'")
    status = import_one_rule(rule, rule_type)
    if status == 'unknown_type':
        raise ValueError(f"Model for '{rule_type}' not loadable")
    return {'rule_type': rule_type, 'status': status}


@mcp.tool()
def import_rules_bulk(payload: dict) -> dict:
    """Bulk import rules.

    Accepts ``{"rule_type": "...", "rules": [<dict>, ...]}`` (single
    type) or ``{"rules": {"<rule_type>": [<dict>, ...], ...}}`` (multi
    type, same shape as ``export_all_rules`` output).
    """
    _current_user()
    counts = import_json_bundle(payload)
    if not counts and not isinstance(payload.get('rules'), (list, dict)):
        raise ValueError("Payload must contain a 'rules' list or dict")
    return {'imported': counts, 'total': sum(counts.values())}


@mcp.tool()
def run_autorules(debug: bool = False) -> dict:
    """Run the autorules pass that builds rules from current host data."""
    _current_user()
    create_rules(account=False, debug=debug)
    return {'status': 'ok'}


# --- Syncer / cron / logs ---------------------------------------------------


@mcp.tool()
def get_recent_logs(limit: int = 100) -> dict:
    """Return the latest *limit* log entries, newest first."""
    _current_user()
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    out = []
    for entry in LogEntry.objects().order_by('-id')[:limit]:
        out.append({
            'entry_id': str(entry.id),
            'time': entry.datetime.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'message': entry.message,
            'source': entry.source,
            'details': [{'name': d.level, 'message': d.message}
                        for d in entry.details],
            'has_error': entry.has_error,
        })
    return {'logs': out}


@mcp.tool()
def get_cron_status() -> dict:
    """Return status of every CronGroup."""
    _current_user()
    out = []
    for entry in CronStats.objects:
        out.append({
            'name': str(entry.group),
            'last_start': (entry.last_start.strftime('%Y-%m-%dT%H:%M:%SZ')
                           if entry.last_start else None),
            'next_run': (entry.next_run.strftime('%Y-%m-%dT%H:%M:%SZ')
                         if entry.next_run else None),
            'is_running': entry.is_running,
            'last_message': entry.last_message,
            'has_error': entry.failure,
        })
    return {'groups': out}


@mcp.tool()
def trigger_cron_group(group_name: str) -> dict:
    """Schedule the named CronGroup to run on the next cron pass."""
    _current_user()
    try:
        group = CronGroup.objects.get(name=group_name)
    except DoesNotExist as exc:
        raise ValueError(f"CronGroup '{group_name}' not found") from exc
    if not group.enabled:
        return {'status': 'disabled', 'group': group_name}
    group.run_once_next = True
    group.save()
    return {'status': 'triggered', 'group': group_name}


@mcp.tool()
def host_stats() -> dict:
    """Aggregate host counters: total, objects, stale (no import seen in 24h)."""
    _current_user()
    ago_24h = datetime.now() - timedelta(hours=24)
    return {
        '24h_checkpoint': ago_24h.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'num_hosts': Host.objects(is_object=False).count(),
        'num_objects': Host.objects(is_object=True).count(),
        'not_updated_last_24h': Host.objects(
            is_object=False, last_import_seen__lt=ago_24h,
        ).count(),
    }


# --- Resources --------------------------------------------------------------


@mcp.resource("cmdbsyncer://hosts/{hostname}")
def host_resource(hostname: str) -> str:
    """Single host record as JSON."""
    _current_user()
    try:
        host = Host.objects.get(hostname=hostname)
    except DoesNotExist:
        return json.dumps({'error': f"Host '{hostname}' not found"})
    return json.dumps(_host_to_dict(host), indent=2)


@mcp.resource("cmdbsyncer://rules/{rule_type}")
def rules_resource(rule_type: str) -> str:
    """Every rule of *rule_type* as a JSON list."""
    _current_user()
    if rule_type not in enabled_rules:
        return json.dumps({'error': f"Unknown rule_type '{rule_type}'"})
    rules = []
    for raw in iter_rules_of_type(rule_type):
        try:
            rules.append(json.loads(raw))
        except (ValueError, TypeError):
            continue
    return json.dumps({'rule_type': rule_type, 'rules': rules}, indent=2)


@mcp.resource("cmdbsyncer://cron/status")
def cron_status_resource() -> str:
    """Cron-group status snapshot as JSON."""
    _current_user()
    return json.dumps(get_cron_status(), indent=2)


# ---------------------------------------------------------------------------
# Per-request Basic Auth middleware (SSE transport only)
# ---------------------------------------------------------------------------


def _request_is_secure(request):
    """Mirror ``application.api._is_secure_api_request``: HTTPS, localhost,
    or the explicit ``ALLOW_INSECURE_API_AUTH`` config flag."""
    if app.config.get('ALLOW_INSECURE_API_AUTH'):
        return True
    if request.url.scheme == 'https':
        return True
    forwarded_proto = request.headers.get('x-forwarded-proto', '').lower()
    if forwarded_proto == 'https' and app.config.get('TRUSTED_PROXIES', 0):
        return True
    client_host = request.client.host if request.client else ''
    return client_host in {'127.0.0.1', '::1'}


def _challenge(message='Unauthorized'):
    """Build a 401 response with a Basic challenge."""
    # starlette / uvicorn are optional deps from ``requirements-extras.txt``
    # — only imported when SSE transport is requested.
    # pylint: disable=import-outside-toplevel,import-error
    from starlette.responses import Response
    return Response(
        message, status_code=401,
        headers={'WWW-Authenticate': 'Basic realm="cmdbsyncer"'},
    )


def _build_auth_middleware():
    """Return a Starlette ``BaseHTTPMiddleware`` subclass.

    Imported lazily so the ``starlette`` dep only loads when the SSE
    transport is requested — stdio mode never imports it.
    """
    # pylint: disable=import-outside-toplevel,import-error
    from starlette.middleware.base import BaseHTTPMiddleware

    class BasicAuthMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
        """Per-request Basic Auth + HTTPS gate. Sets ``_request_user``."""

        async def dispatch(self, request, call_next):  # pylint: disable=missing-function-docstring
            if not _request_is_secure(request):
                return _challenge("HTTPS is required for password-based "
                                  "API authentication")
            auth = request.headers.get('authorization', '')
            if not auth.lower().startswith('basic '):
                return _challenge("Basic Auth required")
            try:
                decoded = base64.b64decode(auth[6:].strip()).decode('utf-8')
                username, password = decoded.split(':', 1)
            except (ValueError, UnicodeDecodeError):
                return _challenge()
            user = _resolve_user(username, password)
            if user is None or not _user_has_mcp_access(user):
                return _challenge()
            token = _request_user.set(user)
            try:
                return await call_next(request)
            finally:
                _request_user.reset(token)

    return BasicAuthMiddleware


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _run_sse(host, port):
    """Build the SSE Starlette app, wrap with auth middleware, run uvicorn."""
    # pylint: disable=import-outside-toplevel,import-error
    import uvicorn

    asgi_app = mcp.sse_app()
    asgi_app.add_middleware(_build_auth_middleware())
    print(f"cmdbsyncer-mcp listening on http://{host}:{port}/sse "
          f"(per-request Basic Auth)", file=sys.stderr)
    uvicorn.run(asgi_app, host=host, port=port, log_level='warning')


def main():
    """Parse credentials, authenticate, run the MCP server."""
    parser = argparse.ArgumentParser(
        prog='cmdbsyncer-mcp',
        description='cmdbsyncer MCP server — exposes hosts, accounts, '
                    'rules, cron and logs over the Model Context Protocol.',
    )
    parser.add_argument(
        '--user', default=os.environ.get('CMDBSYNCER_API_USER'),
        help='stdio-mode user (or CMDBSYNCER_API_USER). Required for '
             'stdio; ignored for sse (which authenticates per request).',
    )
    parser.add_argument(
        '--password', default=os.environ.get('CMDBSYNCER_API_PASSWORD'),
        help='stdio-mode password (or CMDBSYNCER_API_PASSWORD).',
    )
    parser.add_argument(
        '--transport', choices=('stdio', 'sse'),
        default=os.environ.get('CMDBSYNCER_MCP_TRANSPORT', 'stdio'),
        help='stdio (default) — JSON-RPC over stdin/stdout, single user '
             'bound at startup. sse — HTTP server on --host/--port with '
             'per-request Basic Auth and HTTPS gate.',
    )
    parser.add_argument(
        '--host', default=os.environ.get('CMDBSYNCER_MCP_HOST', '127.0.0.1'),
        help='Bind host for sse transport. Default 127.0.0.1.',
    )
    parser.add_argument(
        '--port', type=int,
        default=int(os.environ.get('CMDBSYNCER_MCP_PORT', '8765')),
        help='Bind port for sse transport. Default 8765.',
    )
    args = parser.parse_args()

    if args.transport == 'sse':
        _run_sse(args.host, args.port)
        return

    # stdio mode — single user resolved at startup.
    if not args.user or not args.password:
        _abort(
            "Authentication required for stdio transport.\n"
            "Pass --user and --password, or set CMDBSYNCER_API_USER and "
            "CMDBSYNCER_API_PASSWORD."
        )
    _login_stdio(args.user, args.password)
    mcp.run()  # JSON-RPC over stdin/stdout


if __name__ == '__main__':
    main()
