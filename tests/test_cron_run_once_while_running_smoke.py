"""
A run requested while the group is running (webhook, Run button, API) has to
wait for the next pass of the cron runner, it must not get lost.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import os
from datetime import datetime, timedelta

from application import app, cron_register
from application.models.cron import CronGroup, CronStats, GroupEntry
from application.plugins.cron import jobs

ran = []
cron_register['t: job'] = lambda: ran.append('job')

group = CronGroup(name='busy', interval='hour', enabled=True, run_once_next=True,
                  jobs=[GroupEntry(name='t: job', command='t: job')])
group.save()
stats = CronStats(group='busy', is_running=True, pid=os.getpid())
stats.next_run = datetime.now() + timedelta(hours=1)
stats.save()

# Another process runs the group right now
app.test_cli_runner().invoke(jobs)
eq(ran, [], 'nothing starts while the group is running')
eq(CronGroup.objects.get(name='busy').run_once_next, True, 'request while running')

# That run has ended
stats.reload()
stats.is_running = False
stats.pid = None
stats.save()
app.test_cli_runner().invoke(jobs)
eq(ran, ['job'], 'the request runs in the next pass')
eq(CronGroup.objects.get(name='busy').run_once_next, False, 'request after its run')

app.test_cli_runner().invoke(jobs)
eq(ran, ['job'], 'the request runs only once')
print('CRON_RUN_ONCE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CronRunOnceWhileRunningTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_request_survives_a_running_group(self):
        """The request stays set until the group is free, then runs once."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('CRON_RUN_ONCE_OK', result.stdout)
