"""
A cron pass runs the groups with a pending trigger (webhook, API, Run)
before the scheduled ones, the order stays otherwise.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application import app, cron_register
from application.models.cron import CronGroup, GroupEntry
from application.plugins.cron import jobs

ran = []
for name in ('first', 'second', 'hook', 'button'):
    cron_register[f't: {name}'] = lambda name=name: ran.append(name)

def group(name, sort, **kwargs):
    CronGroup(name=name, interval='hour', enabled=True, sort_field=sort,
              jobs=[GroupEntry(name=f't: {name}', command=f't: {name}')],
              **kwargs).save()

group('first', 1)
group('second', 2)
group('hook', 3, run_once_configs=[{'import_filter': 'name:srv01'}])
group('button', 4, run_once_next=True)

app.test_cli_runner().invoke(jobs)
eq(ran, ['hook', 'button', 'first', 'second'], 'triggered groups first')
print('CRON_TRIGGERED_FIRST_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CronTriggeredFirstTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_triggered_groups_run_first(self):
        """Webhook and Run triggers are ahead of the scheduled groups."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('CRON_TRIGGERED_FIRST_OK', result.stdout)
