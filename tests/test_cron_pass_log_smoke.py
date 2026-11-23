"""
A pass of `cron run_jobs` reports to the log pipeline, not to the Log view.
One entry every few minutes buried the real entries there.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import logging
from datetime import datetime, timedelta

from application import app, cron_register
from application.models.cron import CronGroup, CronStats, GroupEntry
from application.modules.log.models import LogEntry
from application.plugins.cron import jobs


class Collect(logging.Handler):
    """Keeps the records of the external sink"""
    records = []

    def emit(self, record):
        self.records.append(record)


sink = Collect()
logging.getLogger('syslog').addHandler(sink)
logging.getLogger('syslog').setLevel(logging.INFO)

cron_register['t: job'] = lambda: None
CronGroup(name='busy', interval='hour', enabled=True, run_once_next=True,
          jobs=[GroupEntry(name='t: job', command='t: job')]).save()

app.test_cli_runner().invoke(jobs)
CronStats.objects(group='busy').update(set__next_run=datetime.now() + timedelta(hours=1))
app.test_cli_runner().invoke(jobs)

messages = [r.getMessage() for r in sink.records if r.event_source == 'cron']
eq(messages, ['Cron pass', 'Cron pass'],
   'every pass reaches the pipeline')
eq(LogEntry.objects(message__startswith='Cron pass').count(), 0,
   'no pass in the Log view')
print('CRON_PASS_LOG_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CronPassLogTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_pass_goes_to_the_pipeline_only(self):
        """Both kinds of pass are streamed, none is stored."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('CRON_PASS_LOG_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
