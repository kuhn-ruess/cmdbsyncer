"""
Smoke test: one run per export and account. A second run stops, a lock of
a process that is gone is taken over, a dry run is never blocked.
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app

SNIPPET = '''
import os
import socket
from datetime import datetime

from application.helpers import run_lock
from application.helpers.task_status import take_task_failure
from application.models.cron import RunLock

calls = []

@run_lock.exclusive_per_account('Test Export')
def export(account, dry_run=False):
    calls.append((account, dry_run))
    return 'ran'

# Nothing holds the lock: the export runs and gives it back.
eq(export('acc1'), 'ran', 'free run')
eq(RunLock.objects.count(), 0, 'locks after the run')

# A live run on this host holds the lock: the second run is skipped.
RunLock(name='Test Export:acc1', pid=os.getpid(),
        hostname=socket.gethostname(), started=datetime.now()).save()
eq(export('acc1'), None, 'blocked run')
eq(type(take_task_failure()).__name__, 'RunLockedError', 'cron is told')
eq(export(account='acc2'), 'ran', 'other account')
eq(export('acc1', dry_run=True), 'ran', 'dry run')
eq(export('acc1', False), None, 'positional dry_run=False')
eq(RunLock.objects(name='Test Export:acc1').count(), 1, 'foreign lock kept')

# The holder is gone: the lock is taken over and released afterwards.
RunLock.objects(name='Test Export:acc1').update(set__pid=999999)
eq(export('acc1'), 'ran', 'stale lock taken over')
eq(RunLock.objects.count(), 0, 'locks after the takeover run')

# A recreated container has another hostname: a dead PID is still stale.
RunLock(name='Test Export:acc1', pid=999999, hostname='old-container',
        started=datetime.now()).save()
eq(export('acc1'), 'ran', 'lock of a recreated container')
eq(calls, [('acc1', False), ('acc2', False), ('acc1', True), ('acc1', False),
           ('acc1', False)], 'runs')
print('RUN_LOCK_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class RunLockTests(unittest.TestCase):
    """Runs the snippet against the booted app."""

    def test_one_run_per_export_and_account(self):
        """Second run stops, stale lock is taken over."""
        result = run_against_app(SNIPPET, True)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        self.assertIn('RUN_LOCK_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
