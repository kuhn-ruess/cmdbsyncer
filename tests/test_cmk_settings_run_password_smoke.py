"""
Run Playbook of the Checkmk Settings list: the dialog asks before the run
and, when ticked, for the SSH and the sudo password, which reach this run
only. The playbook run itself is replaced.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from unittest.mock import patch
from application.plugins.checkmk.models import CheckmkSettings, CheckmkSite
import application.plugins.checkmk.views as cmk_views

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})
settings = CheckmkSettings(name='Prod', cmk_version='2.4.0p12').save()
CheckmkSite(name='prod', server_address='srv01', settings_master=settings,
            enabled=True).save()

page = client.get('/admin/checkmksettings/').get_data(as_text=True)
for text in ('id="runMngmtModal"', 'name="ask_password"', 'name="become_password"',
             'class="btn btn-primary btn-sm cmk-run-mngmt"'):
    if text not in page:
        fail('list misses ' + text)

calls = []
def fake_run(playbook, **kwargs):
    calls.append(kwargs)
    return type('Stats', (), {'pk': '0' * 24})()

url = f'/admin/checkmksettings/run/{settings.id}'
token = csrf('/admin/checkmksettings/')
with patch.object(cmk_views, 'run_playbook', fake_run):
    client.post(url, data={'csrf_token': token})
    client.post(url, data={'csrf_token': token, 'ask_password': '1',
                           'ssh_password': 'ssh-secret', 'become_password': ''})
    client.post(url, data={'csrf_token': token, 'ask_password': '1',
                           'ssh_password': '', 'become_password': 'sudo-secret'})
    body = client.post(url, data={'csrf_token': token, 'ask_password': '1'},
                       follow_redirects=True).get_data(as_text=True)
logins = [(c.get('ssh_password'), c.get('become_password')) for c in calls]
eq(logins, [(None, None), ('ssh-secret', 'ssh-secret'), (None, 'sudo-secret')], 'logins')
if 'Enter the SSH or the sudo password' not in body:
    fail('empty password dialog not refused')
if any(c['target_host'] != 'srv01' for c in calls):
    fail('targets ' + repr(calls))

# Settings that ask for the SSH password: the form has the box, the button
# opens with the field as must, and no run starts without the password.
edit_url = f'/admin/checkmksettings/edit/?id={settings.id}'
if 'Ask for the SSH password on Run' not in client.get(edit_url).get_data(as_text=True):
    fail('form misses the ask box')
client.post(edit_url, data={'name': 'Prod', 'cmk_version': '2.4.0p12', 'enabled': 'y',
                            'ask_ssh_password': 'y', 'schedule_hour': '0',
                            'csrf_token': csrf(edit_url)}, follow_redirects=True)
settings.reload()
if not settings.ask_ssh_password:
    fail('ask box not saved')
if 'data-ask="1"' not in client.get('/admin/checkmksettings/').get_data(as_text=True):
    fail('button does not ask')
calls.clear()
token = csrf('/admin/checkmksettings/')
with patch.object(cmk_views, 'run_playbook', fake_run):
    body = client.post(url, data={'csrf_token': token},
                       follow_redirects=True).get_data(as_text=True)
    if calls or 'asks for the SSH password' not in body:
        fail('run without the password not refused')
    body = client.post('/admin/checkmksettings/action/', data={
        'action': 'run_server_mngmt', 'rowid': str(settings.id),
        'csrf_token': token}, follow_redirects=True).get_data(as_text=True)
    if calls or 'asks for the SSH password' not in body:
        fail('bulk action without the password not refused')
    client.post(url, data={'csrf_token': token, 'ask_password': '1',
                           'ssh_password': 'ssh-secret'})
eq([c.get('ssh_password') for c in calls], ['ssh-secret'], 'run with password')
print('RUN_PASSWORD_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CmkSettingsRunPasswordTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_run_password(self):
        """No password, SSH password for both, sudo only, none refused."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        self.assertIn('RUN_PASSWORD_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
