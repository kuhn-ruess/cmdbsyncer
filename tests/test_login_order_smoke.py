"""
With the LDAP login on, a local user with the right local password logs in
without the directory: it never sees that password and logs no failed bind.
The directory is asked only when there is no local match.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application import limiter
from application.enterprise import register_feature

limiter.enabled = False
app.config['LDAP_LOGIN'] = True
asked = []
directory_user = {}


def fake_ldap_login(email, password):
    asked.append(email)
    if email == 'alice@example.com' and password == 'directory-password':
        if 'user' not in directory_user:
            user = User(email=email, name='alice')
            user.save()
            directory_user['user'] = user
        return directory_user['user']
    return None


register_feature('ldap_login', fake_ldap_login)


def login(email, password):
    token = csrf('/login')
    response = client.post('/login', data={
        'login_email': email, 'password': password, 'otp': '',
        'login_submit': 'Login', 'csrf_token': token})
    body = response.get_data(as_text=True)
    ok = response.status_code == 302 and 'Wrong Password' not in body
    if ok:
        token = csrf('/logout')
        client.post('/logout', data={'csrf_token': token})
    return ok


# --- a local user with the right local password: the directory stays out
eq(login('smoke@example.com', 'smoke-password'), True, 'local login')
eq(asked, [], 'directory asked for a local user with the right password')

# --- a wrong local password goes to the directory, which refuses it
eq(login('smoke@example.com', 'wrong'), False, 'login with a wrong password')
eq(asked, ['smoke@example.com'], 'directory asked after a wrong local password')

# --- a directory user without a local password logs in through the directory
asked.clear()
eq(login('alice@example.com', 'directory-password'), True, 'directory login')
eq(asked, ['alice@example.com'], 'directory asked for a directory user')

print('LOGIN_ORDER_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class LoginOrderTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_local_password_first(self):
        """The directory is asked only without a local match"""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('LOGIN_ORDER_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
