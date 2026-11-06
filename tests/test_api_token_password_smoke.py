"""
A new password revokes the personal API tokens of that user on the REST API.
The MCP server never took these tokens: it stays with name and password.

The MCP SDK is an optional extra, so a stand-in keeps the stdio login testable
and the test through the real SSE middleware skips without it. See
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import importlib.util
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

from application import limiter, mcp_server as server

limiter.enabled = False

OLD_PASSWORD = 'smoke-password'
NEW_PASSWORD = 'New-Password-2026!x'


def make_user(email):
    new = User(email=email, name=email, api_roles=['all'], roles=['host'])
    new.set_password(OLD_PASSWORD)
    plaintext = new.create_api_token(label='automation')
    new.save()
    return new, plaintext


def browser(email, password):
    """A fresh client, logged in as ``email``"""
    global client
    client = app.test_client()
    token = csrf('/login')
    client.post('/login', data={'login_email': email, 'password': password,
                                'otp': '', 'login_submit': 'Login', 'csrf_token': token})
    return client


def rest(plaintext):
    return app.test_client().get(
        '/api/v1/syncer/logs',
        headers={'Authorization': f'Bearer {plaintext}'}).status_code


def mcp_login(email, password):
    """Who the stdio login of the MCP server lets in"""
    server._AUTH_USER = None
    try:
        server._login_stdio(email, password)
    except SystemExit:
        pass
    return server._AUTH_USER.email if server._AUTH_USER else None


def new_token_in_the_web(email):
    """What the owner does afterwards: log in with the new password, create one"""
    global client
    client = browser(email, NEW_PASSWORD)
    token = csrf('/api-tokens')
    page = client.post('/api-tokens', data={'label': 'next', 'csrf_token': token})
    eq(page.status_code, 200, f'{email}: answer when creating a token')
    return page.get_data(as_text=True), max(
        re.findall(r'cmdb_pat_[A-Za-z0-9_-]+', page.get_data(as_text=True)), key=len)


def own_change(person):
    global client
    client = browser(person.email, OLD_PASSWORD)
    token = csrf('/change-password')
    eq(client.post('/change-password',
                   data={'password': NEW_PASSWORD, 'password_repeat': NEW_PASSWORD,
                         'submit': '1', 'csrf_token': token}).status_code,
       302, 'answer of the password change')


def reset_by_mail(person):
    global client
    with app.app_context():
        link = f"/reset-password/{person.generate_token(purpose='pw_reset')}"
    client = app.test_client()
    token = csrf(link)
    client.post(link, data={'password': NEW_PASSWORD, 'password_repeat': NEW_PASSWORD,
                            'submit': '1', 'csrf_token': token})


def edit_in_admin(person, password):
    global client
    client = browser('smoke@example.com', OLD_PASSWORD)
    url = f'/admin/user/edit/?id={person.id}'
    token = csrf(url)
    eq(client.post(url, data={'email': person.email, 'name': person.name, 'theme': 'default',
                              'roles': list(person.roles), 'api_roles': list(person.api_roles),
                              'password': password, 'csrf_token': token}).status_code,
       302, 'answer of the user form')


def admin_change(person):
    edit_in_admin(person, NEW_PASSWORD)


bystander, bystander_token = make_user('bystander@example.com')

for email, change in (('own@example.com', own_change),
                      ('reset@example.com', reset_by_mail),
                      ('admin@example.com', admin_change)):
    person, old_token = make_user(email)
    eq(rest(old_token), 200, f'{email}: token before the change')
    eq(mcp_login(email, old_token), None, f'{email}: MCP with a token before the change')

    change(person)
    eq(User.objects.get(email=email).check_password(NEW_PASSWORD), True, f'{email}: the change')

    eq(rest(old_token), 401, f'{email}: token after the change')
    eq(mcp_login(email, old_token), None, f'{email}: MCP with the token after the change')
    eq(mcp_login(email, OLD_PASSWORD), None, f'{email}: MCP with the old password')
    eq(mcp_login(email, NEW_PASSWORD), email, f'{email}: MCP with the new password')

    # The record stays and says so, the user sees why the old token is dead
    kept = User.objects.get(email=email).api_tokens
    eq(len(kept), 1, f'{email}: token records after the change')
    eq(bool(kept[0].revoked_at), True, f'{email}: revoked mark')

    page, new_token = new_token_in_the_web(email)
    eq('revoked' in page, True, f'{email}: label in the own token list')
    eq(new_token == old_token, False, f'{email}: a new token was shown')
    eq(rest(new_token), 200, f'{email}: token created after the change')
    eq(mcp_login(email, new_token), None, f'{email}: MCP with the new token')
    eq(rest(old_token), 401, f'{email}: old token next to the new one')

eq(rest(bystander_token), 200, 'token of another user')

# The list in the user management shows the mark too
client = browser('smoke@example.com', OLD_PASSWORD)
page = check('/admin/user/', 200).get_data(as_text=True)
eq('>revoked<' in page, True, 'label in the user management')

# A new token dies with the next password as well, an old mark keeps its time
person = User.objects.get(email='own@example.com')
first_mark = person.api_tokens[0].revoked_at
person.set_password('Another-Password-2026!x')
person.save()
kept = User.objects.get(email='own@example.com').api_tokens
eq(kept[0].revoked_at, first_mark, 'time of the first mark')
eq(bool(kept[1].revoked_at), True, 'token created between two changes')

# Other saves of the user revoke nothing
other, other_token = make_user('other@example.com')
edit_in_admin(other, '')
eq(rest(other_token), 200, 'token after an admin saved the user without a password')
fresh = User.objects.get(email='other@example.com')
fresh.theme = 'default'
fresh.save()
eq(rest(other_token), 200, 'token after an unrelated save')

print('TOKENS_OK')
'''

SSE_SNIPPET = '''
import base64
from uuid import uuid4

from starlette.testclient import TestClient

from application import mcp_server as server

person = User(email='mcp@example.com', name='mcp', api_roles=['mcp'])
person.set_password('old-password')
plaintext = person.create_api_token(label='automation')
person.save()


def status(password):
    """An unknown session, 404, is the first answer behind the login."""
    token = base64.b64encode(f'mcp@example.com:{password}'.encode()).decode()
    client = TestClient(server._build_sse_app(), base_url='https://localhost:8765')
    return client.post(f'/messages/?session_id={uuid4().hex}', json={},
                       headers={'Authorization': f'Basic {token}'}).status_code


eq(status('old-password'), 404, 'the password')
eq(status(plaintext), 401, 'a token as the password')
person.set_password('new-password')
person.save()
eq(status('old-password'), 401, 'the old password')
eq(status('new-password'), 404, 'the new password')
eq(status(plaintext), 401, 'a token as the password afterwards')

print('SSE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class ApiTokenPasswordTests(unittest.TestCase):
    """Runs the snippets against the booted app."""

    def _run(self, snippet, marker):
        result = run_against_app(snippet, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn(marker, result.stdout)

    def test_tokens(self):
        """Own change, reset and admin change revoke the tokens, new ones work."""
        self._run(SNIPPET, 'TOKENS_OK')

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'MCP SDK is not installed')
    def test_mcp_over_sse(self):
        """The SSE transport takes the current password and never a token."""
        self._run(SSE_SNIPPET, 'SSE_OK')
