"""Entry point for the ``cmdbsyncer-mcp`` console script.

Exposes the syncer over the Model Context Protocol (MCP) so Claude
Desktop, Cursor, Cline and other MCP clients can read and write syncer
state. Boots the app in CLI mode (no Flask-Admin, no REST blueprints) so
startup stays under ~250 ms.

Authentication
--------------
Basic Auth — same model as the REST API. Pass credentials via either:

* CLI flags: ``--user <name> --password <pw>``
* Env vars: ``CMDBSYNCER_API_USER`` / ``CMDBSYNCER_API_PASSWORD``

The credentials resolve to a ``User`` document at startup; the user must
not be disabled. Each tool call then re-checks ``User.api_roles`` against
a synthetic path (``objects/...``, ``syncer/...``, ``rules/...``) so the
existing role grants from the REST API apply unchanged.

Transport
---------
Two modes, selected with ``--transport``:

* ``stdio`` (default) — the MCP client launches ``cmdbsyncer-mcp`` as a
  subprocess and talks JSON-RPC over stdin/stdout. CLI flags / env vars
  are the only way to pass credentials.
* ``sse`` — runs as an HTTP server (Starlette/uvicorn) on
  ``--host``/``--port`` (default ``127.0.0.1:8765``). Remote / cloud
  MCP clients connect over Server-Sent Events. Auth is still resolved
  at startup from the same credentials; the MCP session inherits the
  bound user.
"""
import argparse
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
# Auth — single User bound at startup, role check on every tool call.
# ---------------------------------------------------------------------------


_AUTH_USER = None
_AUTH_USERNAME = None


class MCPAuthError(Exception):
    """Raised when a tool call is denied by the api_roles gate."""


def _login(username, password):
    """Resolve a ``User`` from name/email + password. Aborts on failure."""
    global _AUTH_USER, _AUTH_USERNAME  # pylint: disable=global-statement
    user = None
    try:
        user = User.objects.get(
            disabled__ne=True,
            __raw__={'$or': [{'name': username}, {'email': username}]},
        )
    except DoesNotExist:
        _abort(f"Authentication failed: no enabled user '{username}'")
    except MultipleObjectsReturned:
        # Historical duplicate names: pick the first that authenticates.
        user = next(
            (candidate for candidate in User.objects(
                disabled__ne=True,
                __raw__={'$or': [{'name': username}, {'email': username}]},
            ) if candidate.check_password(password)),
            None,
        )
        if user is None:
            _abort(f"Authentication failed: invalid credentials for '{username}'")

    if not user.check_password(password):
        _abort(f"Authentication failed: invalid credentials for '{username}'")
    _AUTH_USER = user
    _AUTH_USERNAME = username


def _require(role_path):
    """Mirror ``application.api.require_token``: at least one of the user's
    api_roles must equal ``'all'`` or be a prefix of *role_path*."""
    if _AUTH_USER is None:
        raise MCPAuthError("Not authenticated")
    roles = _AUTH_USER.api_roles or []
    if any(r == 'all' or role_path.startswith(r) for r in roles):
        return
    raise MCPAuthError(
        f"User '{_AUTH_USERNAME}' has no api_role granting '{role_path}'"
    )


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
    _require('objects')
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
    _require('objects')
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
    _require('objects')
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
    _require('objects')
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
    _require('objects')
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
    _require('objects')
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
    care; only callers with the ``objects`` (or ``all``) api_role can call."""
    _require('objects')
    try:
        return _serialize(get_account_by_name(name))
    except AccountNotFoundError as exc:
        raise ValueError(f"Account '{name}' not found") from exc


# --- Rules ------------------------------------------------------------------


@mcp.tool()
def list_rule_types() -> dict:
    """Return the supported ``rule_type`` idents."""
    _require('rules')
    return {'rule_types': sorted(enabled_rules)}


@mcp.tool()
def export_rules(rule_type: str) -> dict:
    """Export every rule of *rule_type* as a list of dicts."""
    _require('rules')
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
    _require('rules')
    return grouped_rules_export(
        include_hosts=include_hosts,
        include_accounts=include_accounts,
        include_users=include_users,
    )


@mcp.tool()
def create_rule(rule_type: str, rule: dict) -> dict:
    """Create one rule of *rule_type*. The dict shape is the same as the
    export form (one ``Document.to_json()`` per rule)."""
    _require('rules')
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
    _require('rules')
    counts = import_json_bundle(payload)
    if not counts and not isinstance(payload.get('rules'), (list, dict)):
        raise ValueError("Payload must contain a 'rules' list or dict")
    return {'imported': counts, 'total': sum(counts.values())}


@mcp.tool()
def run_autorules(debug: bool = False) -> dict:
    """Run the autorules pass that builds rules from current host data."""
    _require('rules')
    create_rules(account=False, debug=debug)
    return {'status': 'ok'}


# --- Syncer / cron / logs ---------------------------------------------------


@mcp.tool()
def get_recent_logs(limit: int = 100) -> dict:
    """Return the latest *limit* log entries, newest first."""
    _require('syncer')
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
    _require('syncer')
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
    _require('syncer')
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
    _require('syncer')
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
    _require('objects')
    try:
        host = Host.objects.get(hostname=hostname)
    except DoesNotExist:
        return json.dumps({'error': f"Host '{hostname}' not found"})
    return json.dumps(_host_to_dict(host), indent=2)


@mcp.resource("cmdbsyncer://rules/{rule_type}")
def rules_resource(rule_type: str) -> str:
    """Every rule of *rule_type* as a JSON list."""
    _require('rules')
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
    _require('syncer')
    return json.dumps(get_cron_status(), indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Parse credentials, authenticate, run the MCP server."""
    parser = argparse.ArgumentParser(
        prog='cmdbsyncer-mcp',
        description='cmdbsyncer MCP server — exposes hosts, accounts, '
                    'rules, cron and logs over the Model Context Protocol.',
    )
    parser.add_argument(
        '--user', default=os.environ.get('CMDBSYNCER_API_USER'),
        help='Syncer user (or CMDBSYNCER_API_USER env var). Must have at '
             'least one matching api_role for the tools you intend to call.',
    )
    parser.add_argument(
        '--password', default=os.environ.get('CMDBSYNCER_API_PASSWORD'),
        help='Password (or CMDBSYNCER_API_PASSWORD env var).',
    )
    parser.add_argument(
        '--transport', choices=('stdio', 'sse'),
        default=os.environ.get('CMDBSYNCER_MCP_TRANSPORT', 'stdio'),
        help='stdio (default) — JSON-RPC over stdin/stdout. '
             'sse — HTTP/Server-Sent-Events server on --host/--port.',
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

    if not args.user or not args.password:
        _abort(
            "Authentication required.\n"
            "Pass --user and --password, or set CMDBSYNCER_API_USER and "
            "CMDBSYNCER_API_PASSWORD."
        )

    _login(args.user, args.password)
    if args.transport == 'sse':
        # FastMCP exposes ``settings`` for host/port — set them before run().
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        print(f"cmdbsyncer-mcp listening on http://{args.host}:{args.port}/sse "
              f"(user: {_AUTH_USERNAME})", file=sys.stderr)
        mcp.run(transport='sse')
    else:
        mcp.run()  # stdio — JSON-RPC over stdin/stdout


if __name__ == '__main__':
    main()
