"""
Host maintenance and inventory against the real models.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from datetime import datetime, timedelta
from unittest.mock import patch

from application.helpers.host_maintenance import lowercase_all_hostnames
from application.helpers.inventory import run_inventory
from application.models.account import Account
from application.models.field_approval import FieldApproval
from application.models.host import Host
from application.models.host_inventory_tree import HostInventoryTree
from application.plugins.maintenance import _archive_unseen_hosts, mark_stale

utcnow = datetime.utcnow

Account(name='stale-account', type='custom', address='https://example.org',
        custom_fields=[]).save()
account = Account.objects.get(name='stale-account')
old = Host(hostname='stale01.example.com', source_account_id=str(account.id),
           source_account_name=account.name,
           last_import_seen=utcnow() - timedelta(days=40))
old.save()
with patch('application.plugins.maintenance.get_account_by_name',
           return_value={'id': account.id, 'stale_after_days': '30'}):
    mark_stale('stale-account')
old.reload()
eq(old.is_stale, True, 'old host is stale')
if (utcnow() - old.stale_since).days != 0:
    fail(f'stale_since should be the day it was found stale: {old.stale_since}')

for index in range(3):
    Host(hostname=f'unseen{index}.example.com',
         last_import_seen=utcnow() - timedelta(days=40)).save()
unseen = Host.objects(last_import_seen__lte=utcnow() - timedelta(days=30),
                      deleted_at__exists=False).count()
details = []
eq(_archive_unseen_hosts(30, False, False, str(unseen - 1), details), 0, 'more than the limit')
eq(_archive_unseen_hosts(30, False, False, str(unseen), details), unseen, 'exactly the limit')

print('MAINTENANCE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class HostMaintenanceTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_host_maintenance(self):
        """See the checks in SNIPPET."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('MAINTENANCE_OK', result.stdout)
