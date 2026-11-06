"""
Accounts and users hold credentials and password hashes: the command line
exports them, the REST API and MCP don't, not even for a global admin.

The MCP SDK is an optional extra, so a stand-in keeps the tools plain
functions. See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import base64
import json
import types

from application.models.account import Account
from application.plugins.rules.rule_import_export import iter_all_rules, iter_rules_of_type

user.api_roles = ['all']
user.tfa_secret = 'tfa-marker'
user.save()
Account(name='acc', type='csv', address='https://marker.example.com').save()

# The command line: no acting user, everything as before
eq('pwdhash' in next(iter_rules_of_type('users')), True, 'CLI exports users')
eq('marker.example.com' in next(iter_rules_of_type('accounts')), True, 'CLI exports accounts')
types_seen = {name for name, _raw in iter_all_rules(include_accounts=True, include_users=True)}
eq({'accounts', 'users'} <= types_seen, True, 'CLI bulk export')

auth = base64.b64encode(b'smoke@example.com:smoke-password').decode()


def api(path, method='get', **kwargs):
    return getattr(client, method)(f'/api/v1/rules/{path}', base_url='https://localhost',
                                   headers={'Authorization': f'Basic {auth}'}, **kwargs)


def no_secret(response, what):
    body = response.get_data(as_text=True)
    for marker in (user.pwdhash, 'tfa-marker', 'marker.example.com'):
        if marker in body:
            fail(f'{what} leaks {marker}')


for path in ('users', 'accounts', 'export?include_users=1', 'export?include_accounts=1',
             'export?include_users=1&include_accounts=1'):
    response = api(path)
    eq(response.status_code, 403, f'GET {path}')
    no_secret(response, path)

response = api('export')
eq(response.status_code, 200, 'plain export')
no_secret(response, 'plain export')
eq({'accounts', 'users'} & set(response.get_json()['rules']), set(), 'types of the export')
eq(api('custom_attributes').status_code, 200, 'another type')
eq(api('users', method='post', json=[{'email': 'x@example.com'}]).status_code, 403, 'POST users')

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

server._AUTH_USER = user
for rule_type in ('users', 'accounts'):
    try:
        server.export_rules(rule_type)
        fail(f'MCP exports {rule_type}')
    except PermissionError:
        pass
    eq('error' in json.loads(server.rules_resource(rule_type)), True, f'{rule_type} resource')
eq({'accounts', 'users'} & set(server.export_all_rules()['rules']), set(), 'MCP bulk export')
eq(list(iter_rules_of_type('users')), [], 'nothing for an acting user')

print('EXPORT_CLI_ONLY_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class ExportCliOnlyTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_cli_only(self):
        """The command line exports them, REST and MCP don't."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('EXPORT_CLI_ONLY_OK', result.stdout)
