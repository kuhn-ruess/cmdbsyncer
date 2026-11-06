"""
A job's wrapper catches its errors, so the command line gets a message
instead of a traceback. Cron must still count such a task as failed.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application import app, cron_register
from application.models.cron import CronGroup, CronStats, GroupEntry
from application.modules.log.models import LogEntry
from application.modules.plugin import Plugin
from application.plugins.cron import jobs

ran = []

def reporting_job():
    ran.append('reporting')
    Plugin().record_exception(ValueError('reported error'))

def following_job():
    ran.append('following')

def raising_job():
    raise ValueError('raised error')

cron_register['t: reports'] = reporting_job
cron_register['t: follows'] = following_job
cron_register['t: raises'] = raising_job

# The real wrappers, with an account no syncer can be set up for
for name, command in (('t: hosts', 'Checkmk: Export Hosts'),
                      ('t: bi', 'Checkmk: Export BI Rules'),
                      ('t: netbox', 'Netbox: Import Devices')):
    if command not in cron_register:
        fail(f'{command} is not registered: {sorted(cron_register)}')
    cron_register[name] = (lambda real: lambda: real(account='gone'))(cron_register[command])

def run_group(name, commands, continue_on_error=False):
    del ran[:]
    group = CronGroup(name=name, interval='10min', enabled=True, run_once_next=True,
                      continue_on_error=continue_on_error,
                      jobs=[GroupEntry(name=command, command=command) for command in commands])
    group.save()
    app.test_cli_runner().invoke(jobs)
    group.delete()
    return CronStats.objects.get(group=name)

stats = run_group('stops', ['t: reports', 't: follows'])
eq(ran, ['reporting'], 'a reported failure stops the group')
eq(stats.failure, True, 'failure of the group')
eq(stats.last_success_at, None, 'last success of the failed group')
eq(stats.last_message, 'reported error', 'message of the group')

stats = run_group('continues', ['t: reports', 't: follows'], continue_on_error=True)
eq(ran, ['reporting', 'following'], 'continue on error keeps going')
eq(stats.failure, True, 'failure with continue on error')

stats = run_group('clean', ['t: follows'])
eq(stats.failure, False, 'a failure of an earlier group does not stick')
if not stats.last_success_at:
    fail('a clean group has no last success')

recovered = "Cron group 'turns' recovered"
stats = run_group('turns', ['t: raises'])
eq(stats.failure, True, 'failure before the recovery')
eq(LogEntry.objects(message=recovered).count(), 0, 'no recovery while it fails')
run_group('turns', ['t: follows'])
eq(LogEntry.objects(message=recovered).count(), 1, 'the first clean run recovers')
run_group('turns', ['t: follows'])
eq(LogEntry.objects(message=recovered).count(), 1, 'a second clean run recovers nothing')

stats = run_group('raises', ['t: raises', 't: follows'])
eq(ran, [], 'a raising task stops the group')
eq(stats.failure, True, 'failure of a raising task')

for wrapper in ('t: hosts', 't: bi', 't: netbox'):
    stats = run_group(wrapper, [wrapper, 't: follows'])
    eq(ran, [], f'{wrapper} stops the group')
    eq(stats.failure, True, f'failure of {wrapper}')

print('CRON_FAILURE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CronTaskFailureTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_failed_tasks(self):
        """Reported and raised failures both count, a clean run stays clean."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('CRON_FAILURE_OK', result.stdout)
