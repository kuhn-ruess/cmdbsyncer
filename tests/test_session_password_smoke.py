"""
A changed or reset password ends the other sessions of that user. The session
that changed it stays logged in, and other saves of the user touch nothing.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application import limiter

limiter.enabled = False

NEW_PASSWORD = 'New-Password-2026!x'


def make_user(email, **fields):
    new = User(email=email, name=email, roles=['host'], **fields)
    new.set_password('smoke-password')
    new.save()
    return new


def browser(email, password='smoke-password'):
    """A fresh client, logged in as ``email``"""
    global client
    client = app.test_client()
    token = csrf('/login')
    client.post('/login', data={'login_email': email, 'password': password,
                                'otp': '', 'login_submit': 'Login', 'csrf_token': token})
    eq(logged_in(client), True, f'{email} after the login')
    return client


def logged_in(which):
    return which.get('/set-theme').status_code == 200


def change_password(which, password=NEW_PASSWORD):
    global client
    client = which
    token = csrf('/change-password')
    return which.post('/change-password',
                      data={'password': password, 'password_repeat': password,
                            'submit': '1', 'csrf_token': token})


# --- a password change keeps this session and ends the others
person = make_user('person@example.com')
first = browser('person@example.com')
second = browser('person@example.com')
eq(change_password(first).status_code, 302, 'answer of the password change')
eq(logged_in(first), True, 'the session that changed the password')
eq(logged_in(second), False, 'the other session after a password change')
eq(logged_in(browser('person@example.com', NEW_PASSWORD)), True, 'login with the new password')

# --- so does a reset by mail, for every session
reset = make_user('reset@example.com')
running = browser('reset@example.com')
with app.app_context():
    link = f"/reset-password/{reset.generate_token(purpose='pw_reset')}"
client = app.test_client()
token = csrf(link)
client.post(link, data={'password': NEW_PASSWORD, 'password_repeat': NEW_PASSWORD,
                        'submit': '1', 'csrf_token': token})
eq(User.objects.get(email='reset@example.com').check_password(NEW_PASSWORD), True, 'the reset')
eq(logged_in(running), False, 'a running session after a reset')

# --- and setting it in the user management, except for the one doing it
victim = make_user('victim@example.com')
running = browser('victim@example.com')


def edit_in_admin(which, target):
    global client
    client = which
    url = f'/admin/user/edit/?id={target.id}'
    token = csrf(url)
    return which.post(url, data={'email': target.email, 'name': target.name, 'theme': 'default',
                                 'roles': list(target.roles),
                                 'password': NEW_PASSWORD, 'csrf_token': token})


admin_browser = browser('smoke@example.com', 'smoke-password')
eq(edit_in_admin(admin_browser, victim).status_code, 302, 'answer of the user form')
eq(User.objects.get(email='victim@example.com').check_password(NEW_PASSWORD), True, 'admin set it')
eq(logged_in(running), False, 'a running session after an admin set the password')
eq(logged_in(admin_browser), True, 'the admin after changing another user')
eq(edit_in_admin(admin_browser, user).status_code, 302, 'answer for the own user')
eq(logged_in(admin_browser), True, 'the admin after changing the own password there')

# --- other saves of the user end nothing
other = make_user('other@example.com')
running = browser('other@example.com')
fresh = User.objects.get(email='other@example.com')
fresh.theme = 'default'
fresh.last_login = None
fresh.save()
eq(logged_in(running), True, 'session after an unrelated save')

# --- a user without a local password keeps working, until there is one
directory = User(email='directory@example.com', name='directory', roles=['host'])
directory.save()
client = app.test_client()
with client.session_transaction() as session:
    session['_user_id'] = directory.get_id()
    session['_fresh'] = True
eq(logged_in(client), True, 'session of a user without a password')
directory.set_password('smoke-password')
directory.save()
eq(logged_in(client), False, 'that session once a password was set')

# --- the cookie is signed, not encrypted: it must not carry the hash
with app.app_context():
    eq(person.pwdhash in person.get_id(), False, 'password hash in the session id')

# --- a session from before the update has no binding to the password
client = app.test_client()
with client.session_transaction() as session:
    session['_user_id'] = str(other.id)
    session['_fresh'] = True
eq(logged_in(client), False, 'a session without the binding')

print('SESSION_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class SessionPasswordTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_sessions(self):
        """A new password ends the other sessions of the user."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('SESSION_OK', result.stdout)
