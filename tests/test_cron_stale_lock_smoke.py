"""
After a container restart the PID of a lock can belong to another process,
PIDs count up from 1 again. Such a lock must not block the group forever,
a lock of a runner that still works must stay.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import os
from datetime import datetime, timedelta

from application import app, cron_register
from application.models.cron import CronGroup, CronStats, GroupEntry
from application.plugins import cron

ran = []
cron_register['t: job'] = lambda: ran.append('job')

CronGroup(name='locked', interval='hour', enabled=True, run_once_next=True,
          jobs=[GroupEntry(name='t: job', command='t: job')]).save()
run_started = datetime.now() - timedelta(hours=1)
# An alive PID, the one of this process
stats = CronStats(group='locked', is_running=True, pid=os.getpid(),
                  last_start=run_started, next_run=datetime.now())
stats.save()

for process_start, what in ((run_started - timedelta(minutes=1), 'the runner'),
                            (None, 'no /proc')):
    cron._process_start = lambda _pid, start=process_start: start
    app.test_cli_runner().invoke(cron.jobs)
    eq(ran, [], f'lock held by {what}')
    eq(CronStats.objects.get(group='locked').is_running, True, f'lock of {what}')

cron._process_start = lambda _pid: datetime.now() - timedelta(minutes=5)
app.test_cli_runner().invoke(cron.jobs)
eq(ran, ['job'], 'a reused PID frees the group')
eq(CronStats.objects.get(group='locked').is_running, False, 'lock after the run')
print('CRON_STALE_LOCK_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CronStaleLockTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_reused_pid_frees_the_group(self):
        """A PID started after the run is not the runner."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('CRON_STALE_LOCK_OK', result.stdout)
