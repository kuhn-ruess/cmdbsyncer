"""
User restrictions must still bite — in the web UI and on the REST API.

``User.restrict_to_accounts`` and ``User.restrict_to_templates`` are the
only thing standing between a user and hosts that are none of their
business. Both are enforced in two places that do not share a code path:
the Flask-Admin list queries and the ``/api/v1`` endpoints. The existing
API tests in ``tests/test_api.py`` check the logic against a stand-in user
object and heavy patching — they keep passing if the real endpoints stop
consulting the scope at all.

These tests use real ``User``, ``Account`` and ``Host`` documents, log in
over HTTP (session for the UI, Basic auth for the API) and assert what
comes back. Both ``CMDB_MODE`` variants are covered.

The fixture builds four hosts so the two restrictions cannot be confused
with each other:

    host-a  account-a  os:linux     both restricted users see it
    host-b  account-b  os:windows   neither sees it
    host-c  account-a  os:windows   only the account-restricted user
    host-d  account-b  os:linux     only the template-restricted user

The same four exist once more as objects (``object-a`` … ``object-d``),
because the Objects list runs its own query and has to hold the line by
itself.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


FIXTURE = '''
import base64

from application.models.account import Account
from application.models.host import Host

for account_name in ('account-a', 'account-b'):
    Account(name=account_name, type='custom', enabled=True).save()

Host(hostname='linux-template', object_type='template',
     cmdb_match='os:linux').save()

for hostname, account_name, labels, is_object in (
        ('host-a', 'account-a', {'os': 'linux'}, False),
        ('host-b', 'account-b', {'os': 'windows'}, False),
        ('host-c', 'account-a', {'os': 'windows'}, False),
        ('host-d', 'account-b', {'os': 'linux'}, False),
        # The same split once more as objects — the Objects list is a
        # separate query and has to honour the scope on its own.
        ('object-a', 'account-a', {'os': 'linux'}, True),
        ('object-b', 'account-b', {'os': 'windows'}, True),
        ('object-c', 'account-a', {'os': 'windows'}, True),
        ('object-d', 'account-b', {'os': 'linux'}, True),
):
    fixture_host = Host(hostname=hostname, labels=labels, is_object=is_object,
                        source_account_name=account_name)
    # Templates are attached by set_account() during an import; here the
    # hosts are made directly, so ask for the match explicitly.
    fixture_host.get_cmdb_template()
    fixture_host.save()


def make_user(email, accounts=(), templates=()):
    """A global admin whose only limit is the scope handed in."""
    person = User(email=email, name=email, global_admin=True,
                  api_roles=['all'],
                  restrict_to_accounts=list(accounts),
                  restrict_to_templates=list(templates))
    person.set_password('smoke-password')
    person.save()
    return person


make_user('unrestricted@example.com')
make_user('by-account@example.com', accounts=['account-a'])
make_user('by-template@example.com', templates=['linux-template'])


def basic(email):
    """Basic-auth header for one of the fixture users."""
    raw = base64.b64encode(f'{email}:smoke-password'.encode()).decode()
    return {'Authorization': 'Basic ' + raw}
'''


API_SCOPE = FIXTURE + '''
def api_visible(email):
    """Hostnames /objects/all hands to `email`."""
    response = client.get('/api/v1/objects/all?start=0&limit=100',
                          headers=basic(email))
    if response.status_code != 200:
        fail(f'{email}: /objects/all answered {response.status_code}')
    return sorted(entry['hostname'] for entry in response.json['results'])


def expect(email, hostnames):
    """Fail unless `email` sees exactly `hostnames`."""
    seen = api_visible(email)
    if seen != sorted(hostnames):
        fail(f'{email} sees {seen}, expected {sorted(hostnames)}')


everything = api_visible('unrestricted@example.com')
for hostname in ('host-a', 'host-b', 'host-c', 'host-d'):
    if hostname not in everything:
        fail(f'the unrestricted user does not even see {hostname}: {everything}')

# /objects/all lists hosts, not objects — the object-* fixtures below
# are the Objects list's business and must not turn up here.
expect('by-account@example.com', ['host-a', 'host-c'])
expect('by-template@example.com', ['host-a', 'host-d'])

# Reading a host outside the scope must look like it does not exist.
account_auth = basic('by-account@example.com')
check('/api/v1/objects/host-a', 200, headers=account_auth)
check('/api/v1/objects/host-b', 404, headers=account_auth)
check('/api/v1/objects/host-d', 404, headers=account_auth)

template_auth = basic('by-template@example.com')
check('/api/v1/objects/host-d', 200, headers=template_auth)
check('/api/v1/objects/host-c', 404, headers=template_auth)

# Writing: naming a foreign account is refused outright, and so is
# touching a host that belongs to one.
check('/api/v1/objects/host-e', 403, method='post', headers=account_auth,
      json={'account': 'account-b', 'labels': {'os': 'linux'}})
check('/api/v1/objects/host-b', 403, method='post', headers=account_auth,
      json={'account': 'account-a', 'labels': {'os': 'linux'}})
check('/api/v1/objects/host-a', 200, method='post', headers=account_auth,
      json={'account': 'account-a', 'labels': {'os': 'linux'}})

# A refused delete must leave the host alone, not just answer 404.
check('/api/v1/objects/host-b', 404, method='delete', headers=account_auth)
if Host.objects.get(hostname='host-b').deleted_at is not None:
    fail('a delete that answered 404 archived the host anyway')

print('API_SCOPE_OK')
'''


WEB_SCOPE = FIXTURE + '''
import re


SESSIONS = {}


def web_client(email):
    """A logged-in browser session, made once per user.

    Logging in again for every page would run into the rate limit on the
    login form, and the redirect that follows would look like a scope
    failure.
    """
    if email in SESSIONS:
        return SESSIONS[email]
    session = app.test_client()
    body = session.get('/login').get_data(as_text=True)
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body)
    if not token:
        fail('no CSRF token on the login page')
    session.post('/login', data={
        'login_email': email,
        'password': 'smoke-password',
        'otp': '',
        'login_submit': 'Login',
        'csrf_token': token.group(1),
    })
    SESSIONS[email] = session
    return session


def expect_list(email, url, visible, hidden):
    """Fail unless the list at `url` shows `visible` and hides `hidden`."""
    page = web_client(email).get(url)
    if page.status_code != 200:
        fail(f'{email}: GET {url} answered {page.status_code}')
    body = page.get_data(as_text=True)
    for hostname in visible:
        if hostname not in body:
            fail(f'{email}: {url} does not show {hostname}')
    for hostname in hidden:
        if hostname in body:
            fail(f'{email}: {url} leaks {hostname}')


for list_url, prefix in (('/admin/host/', 'host'), ('/admin/Objects/', 'object')):
    expect_list('unrestricted@example.com', list_url,
                visible=[f'{prefix}-a', f'{prefix}-b',
                         f'{prefix}-c', f'{prefix}-d'],
                hidden=[])
    expect_list('by-account@example.com', list_url,
                visible=[f'{prefix}-a', f'{prefix}-c'],
                hidden=[f'{prefix}-b', f'{prefix}-d'])
    expect_list('by-template@example.com', list_url,
                visible=[f'{prefix}-a', f'{prefix}-d'],
                hidden=[f'{prefix}-b', f'{prefix}-c'])

print('WEB_SCOPE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestUserScopeSmoke(unittest.TestCase):
    """Account and template restrictions, end to end."""

    def _run(self, snippet, marker):
        """Run `snippet` for both CMDB_MODE values; assert both succeed."""
        for cmdb_mode in ('False', 'True'):
            with self.subTest(cmdb_mode=cmdb_mode):
                result = run_against_app(snippet, cmdb_mode)
                self.assertEqual(
                    result.returncode, 0,
                    f"CMDB_MODE={cmdb_mode}:\n{result.stdout}\n{result.stderr}")
                self.assertIn(marker, result.stdout)

    def test_rest_api_honours_user_scope(self):
        """Lists, reads, writes and deletes stay inside the user's scope."""
        self._run(API_SCOPE, 'API_SCOPE_OK')

    def test_web_lists_honour_user_scope(self):
        """The Host and Objects lists show only what the user may see."""
        self._run(WEB_SCOPE, 'WEB_SCOPE_OK')


if __name__ == '__main__':
    unittest.main()
