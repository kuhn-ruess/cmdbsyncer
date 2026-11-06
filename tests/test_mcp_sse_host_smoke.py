"""
The SSE transport of the MCP server answers to localhost and MCP_ALLOWED_HOSTS.

The MCP SDK is an optional extra: the test through the real Host check skips
without it. See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import importlib.util
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


PATTERNS_SNIPPET = '''
import types

for name in ('mcp', 'mcp.server'):
    sys.modules[name] = types.ModuleType(name)
sys.modules['mcp.server.fastmcp'] = types.SimpleNamespace(
    FastMCP=lambda _name: types.SimpleNamespace(
        tool=lambda: lambda function: function,
        resource=lambda _uri: lambda function: function))

from application.mcp_server import _allowed_hosts_and_origins as patterns

LOCAL = ['127.0.0.1:*', 'localhost:*', '[::1]:*']

def expect(entry, hosts, origins):
    got_hosts, got_origins = patterns(entry)
    if got_hosts[3:] != hosts or got_hosts[:3] != LOCAL:
        fail(f'{entry}: {got_hosts}')
    if got_origins[3:] != origins:
        fail(f'{entry}: {got_origins}')

expect([], [], [])
for entry in (['syncer.example.com'], ['syncer.example.com:*'], 'syncer.example.com'):
    expect(entry, ['syncer.example.com', 'syncer.example.com:*'],
           ['http://syncer.example.com', 'http://syncer.example.com:*',
            'https://syncer.example.com', 'https://syncer.example.com:*'])
expect(['syncer.example.com:8443'], ['syncer.example.com:8443'],
       ['http://syncer.example.com:8443', 'https://syncer.example.com:8443'])
expect(['[2001:db8::1]'], ['[2001:db8::1]', '[2001:db8::1]:*'],
       ['http://[2001:db8::1]', 'http://[2001:db8::1]:*',
        'https://[2001:db8::1]', 'https://[2001:db8::1]:*'])

print('MCP_PATTERNS_OK')
'''

TRANSPORT_SNIPPET = '''
import base64
import contextlib
import io
from uuid import uuid4

from starlette.testclient import TestClient

from application import mcp_server as server

mcp_user = User(email='mcp@example.com', name='mcp', api_roles=['mcp'])
mcp_user.set_password('secret-password')
mcp_user.save()
token = base64.b64encode(b'mcp@example.com:secret-password').decode()
AUTH = {'Authorization': f'Basic {token}'}
URL = f'/messages/?session_id={uuid4().hex}'


def status(base_url, headers=None):
    """An unknown session, 404, is the first answer behind both checks."""
    client = TestClient(server._build_sse_app(), base_url=base_url)
    return client.post(URL, json={}, headers=headers or AUTH).status_code


def expect(what, got, wanted):
    if got != wanted:
        fail(f'{what}: {got}, wanted {wanted}')


# The default: localhost only
expect('default, localhost', status('https://localhost:8765'), 404)
expect('default, other name', status('https://syncer.example.com'), 421)

app.config['MCP_ALLOWED_HOSTS'] = ['syncer.example.com']
expect('listed name', status('https://syncer.example.com'), 404)
expect('listed name with port', status('https://syncer.example.com:8443'), 404)
expect('localhost stays', status('https://localhost:8765'), 404)
expect('other name', status('https://other.example.com'), 421)
expect('no credentials', status('https://syncer.example.com', {'X-None': '1'}), 401)
expect('own origin', status('https://syncer.example.com', {
    **AUTH, 'Origin': 'https://syncer.example.com'}), 404)
expect('foreign origin', status('https://syncer.example.com', {
    **AUTH, 'Origin': 'https://other.example.com'}), 403)

stderr = io.StringIO()
with contextlib.redirect_stderr(stderr):
    status('https://other.example.com')
if 'MCP_ALLOWED_HOSTS' not in stderr.getvalue():
    fail(f'no hint for the admin: {stderr.getvalue()}')

print('MCP_TRANSPORT_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class McpAllowedHostsTests(unittest.TestCase):
    """Runs the snippets against the booted app."""

    def _run(self, snippet, marker):
        result = run_against_app(snippet, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn(marker, result.stdout)

    def test_patterns(self):
        """A setting becomes the literal patterns the SDK compares with."""
        self._run(PATTERNS_SNIPPET, 'MCP_PATTERNS_OK')

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'MCP SDK is not installed')
    def test_transport(self):
        """Listed names pass the real Host check, others and no login don't."""
        self._run(TRANSPORT_SNIPPET, 'MCP_TRANSPORT_OK')
