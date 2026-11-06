"""
The Archive needs a permission, stays within the scope of a user and doesn't
change anything on a mere GET.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from datetime import datetime

from application import limiter
from application.models.host import Host

# Four users log in, the login allows three per minute
limiter.enabled = False


def make_user(email, roles=(), **fields):
    new = User(email=email, name=email, roles=list(roles), **fields)
    new.set_password('smoke-password')
    new.save()
    return new


def login(email):
    global client, TOKEN
    if email in sessions:
        client, TOKEN = sessions[email]
        return
    client = app.test_client()
    response = client.post('/login', data={
        'login_email': email, 'password': 'smoke-password',
        'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
    })
    eq(response.status_code, 302, f'login of {email}')
    # An empty list has no form to take a token from
    TOKEN = csrf('/set-theme')
    sessions[email] = (client, TOKEN)


def archived(name, account):
    host = Host(hostname=name, source_account_id=account, source_account_name=account,
                deleted_at=datetime(2026, 1, 1), lifecycle_state='archived')
    host.save()
    return host


def is_archived(host):
    current = Host.objects(id=host.id).first()
    return current is not None and current.deleted_at is not None


def exists(host):
    return Host.objects(id=host.id).first() is not None


def bulk(action, *hosts):
    return client.post('/admin/archive/action/', data={
        'action': action, 'rowid': [str(host.id) for host in hosts],
        'url': '/admin/archive/', 'csrf_token': TOKEN,
    })


def restore_row(host):
    return client.post('/admin/archive/restore_row', data={
        'id': str(host.id), 'csrf_token': TOKEN})


sessions = {}
make_user('noroles@example.com')
make_user('hosts@example.com', ['host'])
make_user('limited@example.com', ['host', 'hard_delete'], restrict_to_accounts=['own'])
make_user('reader@example.com', ['host'], readonly=True)

# --- no permission, no Archive
login('noroles@example.com')
own = archived('r1', 'own')
response = client.get('/admin/archive/')
eq(response.status_code in (302, 403), True, 'the list without a permission')
response = client.post('/admin/archive/restore_row', data={'id': str(own.id)})
eq(is_archived(own), True, 'restoring without a permission')

# --- a link changes nothing, not even for a user allowed to restore
login('hosts@example.com')
eq(client.get(f'/admin/archive/restore_row?id={own.id}').status_code, 405, 'GET restore')
eq(is_archived(own), True, 'GET restore leaves the host archived')
eq(client.post('/admin/archive/restore_row', data={'id': str(own.id)}).status_code, 400,
   'POST without a CSRF token')
eq(is_archived(own), True, 'POST without a CSRF token leaves the host archived')

# --- the button in the list works
body = check('/admin/archive/', 200).get_data(as_text=True)
for part in ('action="/admin/archive/restore_row"', f'name="id" value="{own.id}"',
             'title="Restore"'):
    if part not in body:
        fail(f'the row action lacks {part}')
if f'restore_row?id={own.id}' in body:
    fail('the row action is still a link')
eq(restore_row(own).status_code, 302, 'POST restore')
eq(is_archived(own), False, 'POST restore restores')

# --- limited to an account: nothing of the others
own, foreign = archived('own-1', 'own'), archived('foreign-1', 'other')
login('limited@example.com')
body = check('/admin/archive/', 200).get_data(as_text=True)
eq('own-1' in body, True, 'own host in the list')
eq('foreign-1' in body, False, 'foreign host in the list')
eq(client.get(f'/admin/archive/details/?id={foreign.id}').status_code, 302,
   'details of a foreign host')
check(f'/admin/archive/details/?id={own.id}', 200)
restore_row(foreign)
eq(is_archived(foreign), True, 'row restore of a foreign host')
bulk('restore', foreign)
eq(is_archived(foreign), True, 'bulk restore of a foreign host')
bulk('hard_delete', foreign)
eq(exists(foreign), True, 'hard delete of a foreign host')
bulk('restore', own, foreign)
eq(is_archived(own), False, 'bulk restore of the own host')
eq(is_archived(foreign), True, 'bulk restore of both keeps the foreign one')
own = archived('own-2', 'own')
bulk('hard_delete', own, foreign)
eq(exists(own), False, 'hard delete of the own host')
eq(exists(foreign), True, 'hard delete of both keeps the foreign one')

# --- hard delete still needs its role
login('hosts@example.com')
bulk('hard_delete', foreign)
eq(exists(foreign), True, 'hard delete without the role')

# --- read only: looks, but neither row action nor write
login('reader@example.com')
body = check('/admin/archive/', 200).get_data(as_text=True)
eq('restore_row' in body, False, 'row action for a read-only user')
eq(restore_row(foreign).status_code in (302, 403), True, 'restore by a read-only user')
eq(is_archived(foreign), True, 'a read-only user restores nothing')

print('ARCHIVE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class ArchiveAccessTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_archive_access(self):
        """Permission, scope and POST hold for every way in."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('ARCHIVE_OK', result.stdout)
