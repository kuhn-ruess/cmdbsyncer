"""
Several users matching one login string: the MCP login checks all of them.

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
from application.models.user import User

LOGIN = 'shared@example.com'


def make_user(email, name, password):
    new = User(email=email, name=name, api_roles=['mcp'])
    new.set_password(password)
    new.save()


make_user('first@example.com', LOGIN, 'first-password')
make_user(LOGIN, 'second', 'second-password')

checked = []
real_check = User.check_password


def counting_check(self, password):
    checked.append(self.email)
    return real_check(self, password)


User.check_password = counting_check


def login(password):
    checked.clear()
    server._AUTH_USER = None
    try:
        server._login_stdio(LOGIN, password)
    except SystemExit:
        pass
    return server._AUTH_USER.email if server._AUTH_USER else None


eq(login('first-password'), 'first@example.com', 'password of the first user')
eq(sorted(checked), ['first@example.com', LOGIN], 'first user matches: both checked once')
eq(login('second-password'), LOGIN, 'password of the second user')
eq(sorted(checked), ['first@example.com', LOGIN], 'second user matches: both checked once')
eq(login('wrong'), None, 'wrong password')
eq(sorted(checked), ['first@example.com', LOGIN], 'no match: both checked once')

print('MCP_COLLISION_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class McpLoginCollisionTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_every_candidate_is_checked(self):
        """The time of a login doesn't tell which of the users matched."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('MCP_COLLISION_OK', result.stdout)
