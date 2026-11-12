"""
The detail page of a running Ansible run updates the log and the state of
the run in place, from the progress endpoint, instead of reloading.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from datetime import datetime
from application.plugins.ansible.models import AnsibleRunStats

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})
run = AnsibleRunStats(playbook='cmk_server_mngmt.yml', target_host='srv01',
                      status='running', started_at=datetime.now(),
                      log='PLAY [all]\\n', pid=4711).save()
base = '/admin/ansiblerunstats/'

page = check(f'{base}details/?id={run.id}', 200).get_data(as_text=True)
for text in ('data-run-field="log"', 'data-run-field="status"',
             'data-run-field="exit_code"', f'progress/{run.id}'):
    if text not in page:
        fail('details miss ' + text)
if 'location.reload' in page:
    fail('details still reload the page')

data = check(f'{base}progress/{run.id}?since=0', 200).get_json()
eq((data['running'], data['log'], data['length'], data['whole']),
   (True, 'PLAY [all]\\n', 11, False), 'first poll')
if 'Running' not in data['status']:
    fail('status ' + data['status'])

run.log = 'PLAY [all]\\nTASK [x]\\n'
run.save()
data = check(f'{base}progress/{run.id}?since=11', 200).get_json()
eq((data['log'], data['length'], data['whole']), ('TASK [x]\\n', 20, False), 'new lines only')
data = check(f'{base}progress/{run.id}?since=999', 200).get_json()
eq((data['log'], data['whole']), ('PLAY [all]\\nTASK [x]\\n', True), 'offset past the end')

run.status, run.exit_code, run.ended_at = 'success', 0, datetime(2026, 11, 12, 18, 30)
run.log = 'replaced at the end\\n'
run.save()
data = check(f'{base}progress/{run.id}?since=20', 200).get_json()
eq((data['running'], data['whole'], data['log'], data['exit_code'], data['ended_at']),
   (False, True, 'replaced at the end\\n', 0, '12.11.2026 18:30:00'), 'ended run')
page = check(f'{base}details/?id={run.id}', 200).get_data(as_text=True)
if 'progress/' in page:
    fail('ended run still polls')
check(f'{base}progress/0123456789abcdef01234567', 404)

user.global_admin = False
user.roles = ['host']
user.save()
response = client.get(f'{base}progress/{run.id}')
if response.status_code == 200 and response.is_json:
    fail('progress without the Ansible right')
print('RUN_PROGRESS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class AnsibleRunProgressTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_progress(self):
        """New lines only, whole log at the end, right needed."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        self.assertIn('RUN_PROGRESS_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
