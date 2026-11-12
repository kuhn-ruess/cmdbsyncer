"""
The LDAP card of the local_config.py editor: it shows the stored values,
an emptied field goes back to its default, and the login test runs with
the values of the card before they are saved, and is logged.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import os
from application.enterprise import register_feature
from application.helpers.local_config_file import load
from application.modules.log.models import LogEntry

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})
url = '/admin/config/local_config'
# The local_config.py of the smoke app holds the mongomock client, which
# the editor can't parse: it edits a file of its own here.
import application.views.config as config_view
path = os.path.join(os.environ['CMDBSYNCER_CONFIG_DIR'], 'edited_config.py')
with open(path, 'w', encoding='utf-8') as handle:
    handle.write('config = {}\\n')
config_view._local_config_path = lambda: path

def apply(**values):
    form = {'_action': 'apply_preset', 'preset': 'ldap', 'csrf_token': csrf(url)}
    form.update({f'value__{key}': value for key, value in values.items()})
    client.post(url, data=form, follow_redirects=True)

apply(LDAP_LOGIN='true', LDAP_SERVER='ldap://srv01.example.com',
      LDAP_USER_DN_TEMPLATE='uid={username},dc=example,dc=com',
      LDAP_BIND_USER='cn=svc,dc=example,dc=com', LDAP_BIND_PASSWORD='bind-secret',
      LDAP_SEARCH_BASE='dc=example,dc=com', LDAP_SEARCH_FILTER='(mail={email})')
stored = load(path)
if stored.get('LDAP_SERVER') != 'ldap://srv01.example.com':
    fail('preset not applied: ' + repr(stored))

page = client.get(url).get_data(as_text=True)
if 'value="ldap://srv01.example.com"' not in page:
    fail('card does not show the stored server')
if 'bind-secret' in page:
    fail('card shows the bind password')
if 'Fill for Active Directory' not in page:
    fail('fill buttons missing')
if '<strong>Test login</strong>' in page:
    fail('test shown without the enterprise feature')

# Emptied on the card: back to the default, search with the service account
apply(LDAP_USER_DN_TEMPLATE='', LDAP_BIND_PASSWORD='')
stored = load(path)
if 'LDAP_USER_DN_TEMPLATE' in stored:
    fail('emptied template still stored')
if stored.get('LDAP_BIND_PASSWORD') != 'bind-secret':
    fail('empty protected field changed the password')

seen = {}
def fake_check(config, login, password):
    seen.update(config=config, login=login, password=password)
    return {'ok': False, 'steps': [
        {'ok': None, 'text': 'LDAP login attempt', 'details': {}},
        {'ok': False, 'text': 'Failed: Log in as the service account',
         'hint': 'The service account was refused.',
         'details': {'error': 'invalidCredentials'}}]}
register_feature('ldap_check_login', fake_check)
if '<strong>Test login</strong>' not in client.get(url).get_data(as_text=True):
    fail('test not shown with the enterprise feature')

response = client.post(url + '/ldap_check', data={
    'csrf_token': csrf(url), 'value__LDAP_SERVER': 'ldap://srv02.example.com',
    'value__LDAP_USER_DN_TEMPLATE': '', 'value__LDAP_BIND_PASSWORD': '',
    'value__LDAP_AUTO_CREATE': 'false',
    'check_login': 'SRV01@example.com', 'check_password': 'pw'})
if response.status_code != 200 or response.get_json()['ok'] is not False:
    fail('check answer: ' + response.get_data(as_text=True)[:300])
config = seen['config']
if config['LDAP_SERVER'] != 'ldap://srv02.example.com':
    fail('check did not use the card value')
if config['LDAP_BIND_PASSWORD'] != 'bind-secret':
    fail('check did not use the stored password')
if config['LDAP_USER_DN_TEMPLATE'] != '' or config['LDAP_AUTO_CREATE'] is not False:
    fail('check config: ' + repr({k: v for k, v in config.items() if k.startswith('LDAP')}))
if seen['login'] != 'srv01@example.com' or seen['password'] != 'pw':
    fail('check login: ' + repr(seen['login']))
entry = LogEntry.objects(source='AUTH',
                         message='LDAP login test for srv01@example.com: failed').first()
if entry is None or not entry.has_error:
    fail('check not logged as error')
if 'pw' in [detail.message for detail in entry.details]:
    fail('password logged')
print('LDAP_SETUP_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class LdapSetupTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_ldap_card(self):
        """Stored values, reset to default, login test with the card."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        self.assertIn('LDAP_SETUP_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
