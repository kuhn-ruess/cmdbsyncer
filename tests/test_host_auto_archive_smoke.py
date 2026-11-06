"""
What the automatic archive paths do with a host, against the real model
and queries: the Host tests under the stubs never see a Mongo filter.
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


COMMON = '''
import datetime
from unittest.mock import patch

from application.models.host import Host
import application.plugins.maintenance as maintenance

ACCOUNT = {'id': 'acc1', 'stale_after_days': 30, 'auto_archive_when_stale': True}
LONG_AGO = datetime.datetime.utcnow() - datetime.timedelta(days=60)


def stale_host(name):
    """A host its source has not reported for two months."""
    return Host(hostname=name, object_type='host', source_account_id='acc1',
                source_account_name='source', last_import_seen=LONG_AGO,
                is_stale=True, stale_since=LONG_AGO).save()


def archived(name):
    return bool(Host.objects.get(hostname=name).deleted_at)
'''

RESTORE = COMMON + '''
restored = stale_host('restored.example.com')
restored.soft_delete(reason='stale > 30 days')
restored.save()
eq(restored.restore(), True, 'restore of an archived host')
restored.save()
stale_host('untouched.example.com')

with patch.object(maintenance, 'get_account_by_name', return_value=ACCOUNT), \\
        patch.object(maintenance, 'log'):
    maintenance.mark_stale('source')
eq(archived('restored.example.com'), False, 'restored host after mark_stale')
eq(archived('untouched.example.com'), True, 'stale host after mark_stale')

Host.objects(hostname='untouched.example.com').update(
    unset__deleted_at=True)
maintenance._archive_unseen_hosts(30, {'id': 'acc1'}, 'source', None, [])
eq(archived('restored.example.com'), False, 'restored host after maintenance')
eq(archived('untouched.example.com'), True, 'unseen host after maintenance')

restored.reload()
eq(restored.is_stale, False, 'stale flag after restore')
eq(restored.stale_since, None, 'stale_since after restore')

# A host no import ever reported doesn't become one by being restored.
manual = Host(hostname='manual.example.com', object_type='host').save()
manual.soft_delete(reason='manual')
manual.restore()
eq(manual.last_import_seen, None, 'last seen of a never imported host')
print('RESTORE_OK')
'''

NOT_FOUND_ON_IMPORT = COMMON + '''
def imported(name, **fields):
    return Host(hostname=name, object_type='host', source_account_name='source',
                last_import_id='old', **fields).save()


imported('gone.example.com')
imported('protected.example.com', no_autodelete=True)
imported('seen.example.com').update(set__last_import_id='run1')

eq(Host.delete_host_not_found_on_import('source', 'run1'), 1, 'archived hosts')
eq(archived('gone.example.com'), True, 'host the import did not see')
eq(archived('protected.example.com'), False, 'protected host')
eq(archived('seen.example.com'), False, 'host the import saw')
print('NOT_FOUND_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestHostAutoArchive(unittest.TestCase):
    """Real Host model and real Mongo filters on mongomock"""

    def _run(self, snippet, marker):
        result = run_against_app(snippet, False)
        self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")
        self.assertIn(marker, result.stdout)

    def test_restored_host_is_not_archived_again(self):
        """The next maintenance run leaves a restored host alone"""
        self._run(RESTORE, 'RESTORE_OK')

    def test_not_found_on_import_spares_protected_hosts(self):
        """An import doesn't archive a host with no_autodelete"""
        self._run(NOT_FOUND_ON_IMPORT, 'NOT_FOUND_OK')
