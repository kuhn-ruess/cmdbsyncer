"""
The start page warns in the Cron Jobs card when `cron run_jobs` does not run.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from datetime import datetime, timedelta

from application import limiter
from application.models.config import Config
from application.models.cron import CronGroup

limiter.enabled = False
# The admin start page sends to the setup wizard while it is not dismissed
Config(first_steps_dismissed=True).save()

token = csrf('/login')
client.post('/login', data={'login_email': 'smoke@example.com', 'password': 'smoke-password',
                            'otp': '', 'login_submit': 'Login', 'csrf_token': token})

WARNING = 'The cron job does not run'


def start_page():
    return check('/admin/', 200).get_data(as_text=True)


# --- no group: nothing to run, no warning
eq(WARNING in start_page(), False, 'warning without any cron group')

# --- an enabled group, run_jobs never ran
group = CronGroup(name='Nightly', enabled=True)
group.save()
page = start_page()
eq(WARNING in page, True, 'warning when run_jobs never ran')
eq('no pass so far' in page, True, 'never ran is named')
eq('cmdbsyncer cron install' in page, True, 'the fix is named')

# --- the last pass is old
Config.objects().update(set__last_cron_pass=datetime.now() - timedelta(hours=3))
page = start_page()
eq(WARNING in page, True, 'warning after three hours without a pass')
eq('the last pass was 3 h ago' in page, True, 'the age of the last pass')

# --- a recent pass: cron runs
Config.objects().update(set__last_cron_pass=datetime.now() - timedelta(minutes=4))
eq(WARNING in start_page(), False, 'warning although run_jobs ran 4 minutes ago')

# --- only disabled groups: nothing would run anyway
Config.objects().update(unset__last_cron_pass=1)
group.enabled = False
group.save()
eq(WARNING in start_page(), False, 'warning with only disabled groups')

print('HEARTBEAT_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CronHeartbeatTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_start_page_warns_without_cron(self):
        """The warning follows the last run_jobs pass and the enabled groups."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('HEARTBEAT_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
