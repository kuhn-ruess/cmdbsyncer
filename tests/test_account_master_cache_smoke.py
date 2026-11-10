"""
A change of the master flag reaches a running process within the cache time.

The save signal only clears the caches of the process that saved, the
other web workers learn about it when their entry runs out. Saving in
another process is simulated by a direct database update, which sends no
signal. See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from unittest.mock import patch

from application.models import account as account_module
from application.models.account import Account, account_is_master

now = [1000.0]
clock = patch.object(account_module.time, 'monotonic', side_effect=lambda: now[0])
clock.start()

account = Account(name='src', type='csv', address='', enabled=True)
account.save()
eq(account_is_master(str(account.id)), False, 'before the change')

Account.objects(id=account.id).update(set__is_master=True)
now[0] += account_module.IS_MASTER_CACHE_SECONDS - 1
eq(account_is_master(str(account.id)), False, 'within the cache time')

now[0] += 2
eq(account_is_master(str(account.id)), True, 'after the cache time')

clock.stop()
print('MASTER_CACHE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class AccountMasterCacheTests(unittest.TestCase):
    """Runs the snippet against the booted app."""

    def test_master_flag_reaches_a_running_process(self):
        """Cached within the cache time, read again after it."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('MASTER_CACHE_OK', result.stdout)
