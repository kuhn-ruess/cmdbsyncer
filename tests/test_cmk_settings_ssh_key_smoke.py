"""
The Checkmk Settings keep an SSH private key: stored encrypted, kept on an
edit with an empty field, removed on request, a key with passphrase refused.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from application.plugins.checkmk.models import CheckmkSettings

def make_key(encryption=serialization.NoEncryption()):
    return ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        encryption).decode()

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})
key = make_key()

def save(url, **data):
    form = {'name': 'Prod', 'cmk_version': '2.5.0p1', 'enabled': 'y',
            'csrf_token': csrf(url)}
    form.update(data)
    return client.post(url, data=form, follow_redirects=True)

save('/admin/checkmksettings/new/', server_ssh_key=key.replace('\\n', '\\r\\n'))
entry = CheckmkSettings.objects(name='Prod').first()
if entry is None:
    fail('settings not created')
if 'PRIVATE KEY' in entry.server_ssh_key_crypted:
    fail('key stored in plain text')
if entry.get_server_ssh_key() != key:
    fail('stored key differs: ' + repr(entry.get_server_ssh_key()[:40]))

edit_url = f'/admin/checkmksettings/edit/?id={entry.id}'
page = client.get(edit_url).get_data(as_text=True)
if 'A key is stored' not in page:
    fail('edit form does not say a key is stored')
if key.splitlines()[1] in page:
    fail('edit form shows the key')

save(edit_url, server_ssh_key='')
if CheckmkSettings.objects(name='Prod').first().get_server_ssh_key() != key:
    fail('empty field dropped the key')

body = save(edit_url, server_ssh_key=make_key(
    serialization.BestAvailableEncryption(b'secret'))).get_data(as_text=True)
if 'passphrase' not in body:
    fail('key with passphrase not refused')
if CheckmkSettings.objects(name='Prod').first().get_server_ssh_key() != key:
    fail('refused key replaced the stored one')

save(edit_url, remove_server_ssh_key='y')
if CheckmkSettings.objects(name='Prod').first().server_ssh_key_crypted:
    fail('key not removed')
print('SSH_KEY_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CmkSettingsSshKeyTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_ssh_key_lifecycle(self):
        """Encrypted, kept, refused with passphrase, removed."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        self.assertIn('SSH_KEY_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
