"""
The weekly runs of the Checkmk Server Settings bring their own cron group:
protected, every 15 minutes, on while a settings has a schedule.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application.models.cron import CronGroup
from application.plugins.checkmk.models import CheckmkSettings
from application.plugins.checkmk.server_schedule import CRON_TASK, sync_cron_group

group = lambda: CronGroup.objects(name=CRON_TASK).first()

# --- settings without a schedule: no group
plain = CheckmkSettings(name='plain')
plain.save()
eq(group(), None, 'group without any schedule')

# --- a schedule creates the group, protected and on
weekly = CheckmkSettings(name='weekly', schedule_weekday='tue', schedule_hour='3',
                         schedule_update_version=True)
weekly.save()
eq(group() is not None, True, 'group after the first schedule')
eq((group().protected, group().enabled, group().interval), (True, True, '10min'),
   'protected, on, every 15 minutes')
eq([job.command for job in group().jobs], [CRON_TASK], 'task of the group')

# --- the group lists in the cron view and can not be deleted there
client.post('/login', data={'login_email': 'smoke@example.com', 'password': 'smoke-password',
                            'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login')})
eq(CRON_TASK in check('/admin/crongroup/', 200).get_data(as_text=True), True, 'group listed')
client.post('/admin/crongroup/delete/', data={'id': str(group().id), 'csrf_token': csrf('/admin/crongroup/')})
eq(group() is not None, True, 'group deleted from the cron view')

# --- schedule cleared: the group stays, but off
weekly.schedule_weekday = None
weekly.save()
eq(group().enabled, False, 'group on without a schedule')

# --- a weekday without anything to do is no schedule either
weekly.schedule_weekday = 'tue'
weekly.schedule_update_version = False
weekly.save()
eq(group().enabled, False, 'group on with nothing to do')

# --- back on, then off again when the settings is deleted
weekly.schedule_run_playbook = True
weekly.save()
eq(group().enabled, True, 'group on again')
weekly.delete()
eq(group().enabled, False, 'group on after the settings was deleted')

# --- self_configure path: a sync without changes keeps it as it is
sync_cron_group()
eq(CronGroup.objects(name=CRON_TASK).count(), 1, 'one group only')
print('CRON_GROUP_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CheckmkScheduleCronGroupTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_cron_group_follows_the_schedules(self):
        """Created on the first schedule, on while there is one"""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('CRON_GROUP_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
