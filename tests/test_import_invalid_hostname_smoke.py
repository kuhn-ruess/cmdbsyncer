"""
An invalid hostname in the middle of an import skips that record only: the
hosts after it are imported, the run's log entry names the skipped one.
It used to stop the whole run at the first invalid name.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from unittest.mock import MagicMock

from application.models.account import Account
from application.models.host import Host
from application.modules.log.models import LogEntry
from application.plugins.op5.op5 import Op5

Account(name='op5', type='op5', address='https://op5.example.com', username='api',
        enabled=True, object_type='host', check_for_valid_hostname=True).save()

op5 = Op5('op5')
op5.name = 'OP5 Monitor: Import Hosts'
op5.source = 'op5_import'
answer = [{'name': 'srv01', 'address': '192.0.2.1'},
          {'name': 'bad_name!', 'address': '192.0.2.2'},
          {'name': 'srv03', 'address': '192.0.2.3'}]
op5.inner_request = MagicMock(return_value=MagicMock(json=MagicMock(return_value=answer)))
op5.import_objects()
op5.save_log()

eq(sorted(Host.objects.scalar('hostname')), ['srv01', 'srv03'], 'imported hosts')
entry = LogEntry.objects(source='op5_import').order_by('-datetime').first()
details = {detail.level: detail.message for detail in entry.details}
eq(details.get('skipped'), '1 record(s) skipped for an invalid hostname: bad_name!',
   'skip in the log of the run')
print('INVALID_SKIP_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class InvalidHostnameImportTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_import_goes_on_after_an_invalid_hostname(self):
        """Only the invalid record is skipped"""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('INVALID_SKIP_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
