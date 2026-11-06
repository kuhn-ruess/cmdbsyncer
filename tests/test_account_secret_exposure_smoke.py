"""
Account secrets reach a host's cache through rule outcomes and the debug page
through the {{ACCOUNT:...}} macro. Neither hands them to a user who may not
manage accounts.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application import limiter
from application.helpers.get_account import SECRET_PLACEHOLDER, mask_account_secrets
from application.helpers.syncer_jinja import render_jinja
from application.models.account import Account, CustomEntry
from application.models.host import Host

limiter.enabled = False

SECRET = 'very-secret-value'


def login(email, roles):
    global client
    new = User(email=email, name=email, roles=roles)
    new.set_password('smoke-password')
    new.save()
    client = app.test_client()
    client.post('/login', data={
        'login_email': email, 'password': 'smoke-password',
        'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
    })


# --- the macro: real value in a run, placeholder on the debug page
account = Account(name='acc', type='csv', address='https://acc.example.com', username='user',
                  custom_fields=[CustomEntry(name='api_token', value=SECRET),
                                 CustomEntry(name='bakery_passphrase', value=SECRET),
                                 CustomEntry(name='site', value='plain-value')])
account.save()
for field in ('api_token', 'bakery_passphrase'):
    eq(render_jinja('{{ACCOUNT:acc:' + field + '}}'), SECRET, f'{field} in a run')
    with mask_account_secrets() as masking:
        eq(render_jinja('{{ACCOUNT:acc:' + field + '}}'), SECRET_PLACEHOLDER, f'{field} masked')
    eq(masking.used, True, f'masking of {field} is reported')
with mask_account_secrets():
    eq(render_jinja('{{ACCOUNT:acc:site}}'), 'plain-value', 'a plain field stays readable')
    eq(render_jinja('{{ACCOUNT:acc:address}}'), 'https://acc.example.com', 'the address too')

# --- the cache: values only with the account role
host = Host(hostname='cached', source_account_id='acc', source_account_name='acc',
            cache={'checkmk_rules': {'outcome': SECRET}})
host.save()
url = f'/admin/host/details/?id={host.id}'

login('hosts@example.com', ['host'])
body = check(url, 200).get_data(as_text=True)
eq('1 cache entrie(s)' in body, True, 'the count stays')
eq(SECRET in body, False, 'the value without the account role')
eq('View Cache Details' in body, False, 'the button without the account role')

login('accounts@example.com', ['host', 'account'])
body = check(url, 200).get_data(as_text=True)
eq(SECRET in body, True, 'the value with the account role')

print('SECRET_EXPOSURE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class AccountSecretExposureTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_exposure(self):
        """Debug page and cache keep the secret from those without the role."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('SECRET_EXPOSURE_OK', result.stdout)
