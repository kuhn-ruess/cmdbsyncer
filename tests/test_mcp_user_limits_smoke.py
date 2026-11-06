"""
The MCP tools honour read only and the limits to accounts or templates.

The MCP SDK is an optional extra, so a stand-in keeps the tools plain
functions. See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import types

class FastMCP:
    def __init__(self, _name):
        pass
    def tool(self):
        return lambda function: function
    def resource(self, _uri):
        return lambda function: function

for name in ('mcp', 'mcp.server'):
    sys.modules[name] = types.ModuleType(name)
sys.modules['mcp.server.fastmcp'] = types.SimpleNamespace(FastMCP=FastMCP)

from application import mcp_server as server
from application.models.account import Account
from application.models.cron import CronGroup
from application.models.host import Host
from application.models.user import User


def make_user(email, **fields):
    new = User(email=email, name=email, api_roles=['mcp'], **fields)
    new.set_password('secret-password')
    new.save()
    return new


def host(name, account):
    new = Host(hostname=name, source_account_id=account, source_account_name=account)
    new.save()
    return new


def denied(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except PermissionError:
        return True
    return False


def account_of(name):
    Account(name=name, type='csv', password='account-password', enabled=True).save()


account_of('own')
account_of('other')
host('in-scope', 'own')
host('out-of-scope', 'other')
CronGroup(name='group', enabled=True).save()

admin = make_user('admin@example.com', global_admin=True)
plain = make_user('plain@example.com')
reader = make_user('reader@example.com', readonly=True)
reading_admin = make_user('radmin@example.com', global_admin=True, readonly=True)
limited = make_user('limited@example.com', restrict_to_accounts=['own'])
limited_admin = make_user('ladmin@example.com', global_admin=True,
                          restrict_to_accounts=['own'])

WRITING = (
    (server.upsert_host, ('in-scope', 'own', {'a': 'b'})),
    (server.delete_host, ('in-scope',)),
    (server.update_host_inventory, ('in-scope', 'key', {'a': 'b'})),
    (server.create_rule, ('custom_attributes', {'name': 'x'})),
    (server.import_rules_bulk, ({'rules': {}},)),
    (server.run_autorules, ()),
    (server.trigger_cron_group, ('group',)),
)

# --- read only: no writing tool, every reading one
server._AUTH_USER = reader
for function, args in WRITING:
    eq(denied(function, *args), True, f'{function.__name__} for a read-only user')
eq(server.get_host('in-scope')['hostname'], 'in-scope', 'read only reads a host')
eq(server.list_hosts()['size'], 2, 'read only lists all hosts')
eq([a['name'] for a in server.list_accounts()['accounts']], ['own', 'other'],
   'read only lists accounts')
eq('rule_type' in server.export_rules('custom_attributes'), True, 'read only exports')
eq('groups' in server.get_cron_status(), True, 'read only reads cron')
eq('logs' in server.get_recent_logs(), True, 'read only reads logs')
eq(denied(server.get_account, 'own'), True, 'get_account for a read-only user')

# --- limited to an account: its hosts, nothing global
for user in (limited, limited_admin):
    server._AUTH_USER = user
    eq([h['hostname'] for h in server.list_hosts()['results']], ['in-scope'], 'list_hosts')
    eq(server.list_hosts()['size'], 1, 'size of list_hosts')
    eq(server.host_stats()['not_updated_last_24h'] <= 1, True, 'host_stats')
    eq(server.host_stats()['num_hosts'], 1, 'host_stats counts the scope only')
    try:
        server.get_host('out-of-scope')
        fail('get_host reached a host out of scope')
    except ValueError:
        pass
    eq('error' in server.host_resource('out-of-scope'), True, 'host resource')
    eq(server.delete_host('out-of-scope')['status'], 'not_found', 'delete out of scope')
    eq(server.update_host_inventory('out-of-scope', 'k', {'a': 'b'})['status'], 'not_found',
       'inventory out of scope')
    eq(server.upsert_host('out-of-scope', 'own', {'a': 'b'})['status'], 'account_conflict',
       'upsert out of scope')
    eq(Host.objects.get(hostname='out-of-scope').source_account_name, 'other',
       'the host stays with its account')
    eq(denied(server.upsert_host, 'new', 'other', {}), True, 'upsert into a foreign account')
    for function, args in (
            (server.list_accounts, ()), (server.get_account, ('own',)),
            (server.export_rules, ('custom_attributes',)), (server.export_all_rules, ()),
            (server.rules_resource, ('custom_attributes',)),
            (server.create_rule, ('custom_attributes', {'name': 'x'})),
            (server.import_rules_bulk, ({'rules': {}},)), (server.run_autorules, ()),
            (server.get_recent_logs, ()), (server.get_cron_status, ()),
            (server.cron_status_resource, ()), (server.trigger_cron_group, ('group',))):
        eq(denied(function, *args), True, f'{function.__name__} for a limited user')
    eq('rule_types' in server.list_rule_types(), True, 'the catalog stays open')

server._AUTH_USER = limited
eq(server.upsert_host('created', 'own', {'a': 'b'})['status'], 'saved', 'upsert a new host')
eq(server.upsert_host('in-scope', 'own', {'a': 'b'})['status'], 'saved', 'upsert in scope')
eq(server.update_host_inventory('in-scope', 'k', {'a': 'b'})['status'], 'saved',
   'inventory in scope')
eq(server.delete_host('created')['status'], 'deleted', 'delete in scope')

# --- get_account: the unlimited global admin only
for user in (plain, reader, reading_admin, limited, limited_admin):
    server._AUTH_USER = user
    eq(denied(server.get_account, 'own'), True, f'get_account for {user.email}')
server._AUTH_USER = admin
eq(server.get_account('own')['name'], 'own', 'get_account for the global admin')

# --- an unlimited user keeps everything else
server._AUTH_USER = plain
eq(server.trigger_cron_group('group')['status'], 'triggered', 'plain user triggers cron')
eq(server.delete_host('out-of-scope')['status'], 'deleted', 'plain user deletes any host')

print('MCP_LIMITS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class McpUserLimitsTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_limits(self):
        """Read only and the limits hold in every tool."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('MCP_LIMITS_OK', result.stdout)
