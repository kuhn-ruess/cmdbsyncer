"""
Settings, LDAP Login Test: the preconditions of the LDAP login, the settings
in use and a test login against them.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application import limiter
from application.enterprise import register_feature
from application.modules.log.models import LogEntry

limiter.enabled = False
URL = '/admin/ldap_login_test/'


def login(email, password):
    token = csrf('/login')
    client.post('/login', data={'login_email': email, 'password': password,
                                'otp': '', 'login_submit': 'Login', 'csrf_token': token})


# --- LDAP_LOGIN on, but no enterprise LDAP login: the login says why in the log
app.config['LDAP_LOGIN'] = True
app.config['LDAP_SERVER'] = 'ldaps://ldap.example.com'
app.config['LDAP_BIND_PASSWORD'] = 'service-secret'
token = csrf('/login')
client.post('/login', data={'login_email': 'directory@example.com', 'password': 'x',
                            'otp': '', 'login_submit': 'Login', 'csrf_token': token})
entry = LogEntry.objects(source='AUTH', message__contains='not active').first()
eq(entry is not None, True, 'log entry for an LDAP login that cannot run')

login('smoke@example.com', 'smoke-password')

# --- the page names what is missing and the settings, never a password
page = check(URL, 200).get_data(as_text=True)
eq('Feature ldap_login licensed' in page, True, 'precondition of the feature')
eq('Wrong Password' in page, True, 'what a failing precondition means')
eq('ldaps://ldap.example.com' in page, True, 'the server in use')
eq('service-secret' in page, False, 'the service password on the page')

# --- without the enterprise test the test says so
token = csrf(URL)
page = check(URL, 200, method='post', data={
    'login': 'alice', 'password': 'pw', 'csrf_token': token}).get_data(as_text=True)
eq('The LDAP login test is not available' in page, True, 'test without enterprise')

# --- with it, the running configuration is tested and the steps are shown
seen = {}


def fake_check(config, login_name, password):
    seen.update(server=config.get('LDAP_SERVER'), login=login_name, password=password)
    return {'ok': False, 'steps': [
        {'ok': True, 'text': 'Connected', 'details': {'server': 'ldap.example.com'}},
        {'ok': False, 'text': 'Failed: bind refused', 'hint': 'Check the password',
         'details': {'error': 'invalidCredentials'}},
    ]}


register_feature('ldap_check_login', fake_check)
token = csrf(URL)
page = check(URL, 200, method='post', data={
    'login': ' Alice@Example.com ', 'password': 'pw', 'csrf_token': token}).get_data(as_text=True)
eq(seen, {'server': 'ldaps://ldap.example.com', 'login': 'alice@example.com',
          'password': 'pw'}, 'what the test ran with')
eq('Failed: bind refused' in page and 'Check the password' in page, True, 'the steps')
eq('The login fails' in page, True, 'the result')
entry = LogEntry.objects(source='AUTH', message='LDAP login test for alice@example.com: failed')
eq(entry.count(), 1, 'log entry of the test')

# --- only global admins
plain = User(email='plain@example.com', name='plain', global_admin=False)
plain.set_password('plain-password')
plain.save()
check('/logout', 200)
token = csrf('/logout')
client.post('/logout', data={'csrf_token': token})
login('plain@example.com', 'plain-password')
eq(client.get(URL).status_code in (302, 403), True, 'page for a user without admin rights')

print('LDAP_TEST_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class LdapLoginTestPageTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_ldap_login_test_page(self):
        """Preconditions, settings and the test login"""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('LDAP_TEST_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
