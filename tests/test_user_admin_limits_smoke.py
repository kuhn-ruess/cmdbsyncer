"""
The ``user`` role manages users, it must not lead to more rights than its
holder already has: no global admin, no roles they don't hold themselves, no
hand on anyone with more rights, no way out of their own scope and no view of
2FA secrets.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
def make(email, **fields):
    """A saved user with the smoke password."""
    person = User(email=email, name=email, **fields)
    person.set_password('smoke-password')
    person.save()
    return person


def login(email):
    """Switch ``client`` to a fresh session of ``email``."""
    global client  # pylint: disable=global-statement
    client = app.test_client()
    client.post('/login', data={
        'login_email': email, 'password': 'smoke-password', 'otp': '',
        'login_submit': 'Login', 'csrf_token': csrf('/login'),
    })
    check('/admin/user/', 200)


def save(person, **fields):
    """Post the edit form of ``person``, changing only ``fields``."""
    url = f'/admin/user/edit/?id={person.id}'
    data = {'name': person.name, 'email': person.email, 'theme': 'default',
            'roles': list(person.roles), 'api_roles': list(person.api_roles),
            'csrf_token': csrf(url)}
    data.update(fields)
    return client.post(url, data=data)


def out_of_reach(person, what):
    """No write path may touch ``person``."""
    url = f'/admin/user/edit/?id={person.id}'
    token = csrf('/admin/user/new/')
    hash_before = person.pwdhash
    check(url, 403)
    check(url, 403, method='post', data={
        'name': 'x', 'email': person.email, 'theme': 'default',
        'password': 'hijacked', 'csrf_token': token})
    check('/admin/user/delete/', 403, method='post', data={
        'id': str(person.id), 'csrf_token': token})
    client.post('/admin/user/action/', data={
        'action': 'delete', 'rowid': [str(person.id)], 'csrf_token': token})
    check(f'/admin/user/revoke-token/{person.id}/anything', 403, method='post',
          data={'csrf_token': token})
    check('/admin/user/ajax/update/', 403, method='post', data={
        'list_form_pk': str(person.id), 'disabled': 'y', 'csrf_token': token})
    person.reload()
    eq(person.pwdhash, hash_before, f'password of {what}')
    eq(person.disabled, False, f'disabled on {what}')


admin = make('admin@example.com', global_admin=True)
manager = make('manager@example.com', roles=['user', 'host'],
               api_roles=['objects'])
colleague = make('colleague@example.com', roles=['host'],
                 tfa_secret='COLLEAGUESECRET', restrict_to_accounts=['acc-c'])
senior = make('senior@example.com', roles=['account'])
api_senior = make('api-senior@example.com', api_roles=['all'])
limited = make('limited@example.com', roles=['user'],
               restrict_to_accounts=['acc-a'])
inside = make('inside@example.com', restrict_to_accounts=['acc-a'])
outside = make('outside@example.com', restrict_to_accounts=['acc-b'])
unlimited = make('unlimited@example.com')

login('manager@example.com')

# Set after the login, which would ask for a code otherwise.
manager.tfa_secret = 'MANAGERSECRET'
manager.save()

# The fields are gone from the forms and the list.
for url in ('/admin/user/new/', f'/admin/user/edit/?id={colleague.id}'):
    body = check(url, 200).get_data(as_text=True)
    for field in ('global_admin', 'tfa_secret', 'restrict_to_accounts',
                  'restrict_to_templates'):
        if f'name="{field}"' in body:
            fail(f'{url} still offers {field}')
    if 'COLLEAGUESECRET' in body or 'acc-c' in body:
        fail(f'{url} shows the 2FA secret or the scope')
if 'acc-c' in check('/admin/user/', 200).get_data(as_text=True):
    fail('the list shows the scope')

# Posting them anyway changes nothing.
save(manager, global_admin='y', tfa_secret='TAMPERED')
manager.reload()
eq(manager.global_admin, False, 'global_admin set on oneself')
eq(manager.tfa_secret, 'MANAGERSECRET', 'tfa_secret after tampering')

save(colleague, restrict_to_accounts='')
colleague.reload()
eq(colleague.restrict_to_accounts, ['acc-c'], 'scope after tampering')

url = '/admin/user/new/'
client.post(url, data={
    'name': 'new', 'email': 'new@example.com', 'theme': 'default',
    'global_admin': 'y', 'roles': ['host'], 'csrf_token': csrf(url)})
eq(User.objects.get(email='new@example.com').global_admin, False,
   'global_admin on a created user')

# A password can still be set on someone with no more rights.
save(colleague, password='changed-by-manager')
colleague.reload()
eq(colleague.check_password('changed-by-manager'), True,
   'password of a user with fewer rights')

# Only roles the manager holds can be granted.
save(colleague, roles=['host', 'user'])
colleague.reload()
eq(sorted(colleague.roles), ['host', 'user'], 'granting an own role')

save(colleague, roles=['host', 'user', 'cron'])
colleague.reload()
eq(sorted(colleague.roles), ['host', 'user'], 'granting a foreign role')

save(manager, roles=['user', 'host', 'account'])
manager.reload()
eq(sorted(manager.roles), ['host', 'user'], 'granting oneself a foreign role')

save(colleague, api_roles=['objects'])
colleague.reload()
eq(colleague.api_roles, ['objects'], 'granting an own API role')

save(colleague, api_roles=['objects', 'all'])
colleague.reload()
eq(colleague.api_roles, ['objects'], 'granting a foreign API role')

url = '/admin/user/new/'
client.post(url, data={
    'name': 'new2', 'email': 'new2@example.com', 'theme': 'default',
    'roles': ['account'], 'csrf_token': csrf(url)})
if User.objects(email='new2@example.com').first():
    fail('created a user with a foreign role')

# Anyone with more rights is out of reach, not only global admins.
out_of_reach(admin, 'a global admin')
out_of_reach(senior, 'a user with a foreign role')
out_of_reach(api_senior, 'a user with a foreign API role')

# A limited user can't get out of the limit, not by any detour.
login('limited@example.com')
limited.reload()
save(limited, restrict_to_accounts='')
limited.reload()
eq(limited.restrict_to_accounts, ['acc-a'], 'own scope after a self edit')

out_of_reach(unlimited, 'a user without a scope')
out_of_reach(outside, 'a user with another scope')
check(f'/admin/user/edit/?id={inside.id}', 200)

url = '/admin/user/new/'
client.post(url, data={
    'name': 'new3', 'email': 'new3@example.com', 'theme': 'default',
    'password': 'smoke-password', 'csrf_token': csrf(url)})
eq(User.objects.get(email='new3@example.com').restrict_to_accounts, ['acc-a'],
   'scope of a user created by a limited user')

# A global admin keeps everything.
login('admin@example.com')
body = check(f'/admin/user/edit/?id={colleague.id}', 200).get_data(as_text=True)
for field in ('global_admin', 'tfa_secret', 'restrict_to_accounts'):
    if f'name="{field}"' not in body:
        fail(f'a global admin lost {field} in the form')
if 'acc-c' not in check('/admin/user/', 200).get_data(as_text=True):
    fail('a global admin does not see the scope in the list')
save(colleague, roles=['cron'], api_roles=['all'], global_admin='y',
     tfa_secret='')
colleague.reload()
eq(colleague.roles, ['cron'], 'roles set by a global admin')
eq(colleague.api_roles, ['all'], 'API roles set by a global admin')
eq(colleague.global_admin, True, 'global_admin set by a global admin')
eq(colleague.tfa_secret or '', '', 'tfa_secret cleared by a global admin')
check('/admin/user/delete/', 302, method='post', data={
    'id': str(colleague.id), 'csrf_token': csrf('/admin/user/new/')})
if User.objects(email='colleague@example.com').first():
    fail('a global admin could not delete a global admin')

print('USER_LIMITS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class UserAdminLimitsTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_user_role_stays_within_its_own_rights(self):
        """Forms, role changes and global admins hold the line."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertIn('USER_LIMITS_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
