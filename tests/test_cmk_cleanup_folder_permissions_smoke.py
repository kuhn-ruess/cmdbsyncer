"""
Smoke test: the Checkmk Cleanup Folder Permissions lists the folders with
set permissions and removes them for the selected folders.
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app

SNIPPET = '''
from application.models.account import Account
from application.plugins.checkmk import data_quality

Account(name='cmk-test', type='cmkv2', enabled=True).save()

data_quality.find_folder_permissions = lambda account: {
    'folders': [{'path': '/site7', 'title': 'Site 7', 'groups': ['team_a']}],
    'total': 3}
removed = []
def fake_start(account, paths):
    removed.append((account, paths))
data_quality.start_folder_permissions_cleanup = fake_start

client.post('/login', data={'login_email': 'smoke@example.com',
                            'password': 'smoke-password', 'otp': '',
                            'login_submit': 'Login', 'csrf_token': csrf('/login')})
base = '/admin/checkmk_cleanup_folder_permissions/'
page = check(base, 200).get_data(as_text=True)
if 'Find folders with set permissions' not in page:
    fail('cleanup page missing')
if 'Find folders with set permissions' in check(
        '/admin/checkmk_data_quality/', 200).get_data(as_text=True):
    fail('cleanup still on the Data Quality page')
page = check(base, 200, method='post',
             data={'account': 'cmk-test', 'csrf_token': csrf(base)}
             ).get_data(as_text=True)
if 'value="/site7"' not in page or 'team_a' not in page:
    fail('folder list missing')
check(base + 'remove', 302, method='post',
      data={'account': 'cmk-test', 'folders': ['/site7'],
            'csrf_token': csrf(base)})
if removed != [('cmk-test', ['/site7'])]:
    fail(f'removal not started: {removed}')
print('CLEANUP_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class DataQualityCleanupTests(unittest.TestCase):
    """Runs the snippet against the booted app."""

    def test_folder_permissions_cleanup(self):
        """List and remove the set folder permissions."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        self.assertIn('CLEANUP_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
