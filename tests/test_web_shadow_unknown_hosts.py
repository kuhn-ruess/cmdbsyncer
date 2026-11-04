"""
Hosts a shadow source delivers but the syncer does not know must show up in
the log: with an exact count, a bounded list of names and per account, also
when the import runs thousands of them through one process.

Runs against the real app like ``tests/test_web_requests_smoke.py``, see
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


UNKNOWN_HOSTS = LOGIN + '''
import atexit
from application.helpers.import_hostnames import update_import_host
from application.helpers.shadow_data import UNKNOWN_HOST_SAMPLE
from application.models.host import Host
from application.modules.log.models import LogEntry


def verify():
    """Registered first, so it runs after the log entries were written."""
    eq(sorted(h.hostname for h in Host.objects()), ['known'], 'hosts in the database')

    big = LogEntry.objects.get(message='Shadow source big: 5000 host(s) not in Syncer')
    eq(big.source, 'shadow_source', 'log source')
    eq(big.has_error, False, 'flagged as error')
    eq(big.affected_hosts, [], 'affected hosts')
    details = {detail.level: detail.message for detail in big.details}
    eq(details['account'], 'big', 'account detail')
    names = details['not_in_syncer']
    eq(names.count('big-'), UNKNOWN_HOST_SAMPLE, 'names kept')
    if not names.endswith(f'and {5000 - UNKNOWN_HOST_SAMPLE} more'):
        fail(f'the hidden hosts are not counted: {names[-40:]}')

    small = LogEntry.objects.get(message='Shadow source small: 1 host(s) not in Syncer')
    eq(small.details[1].message, 'small-host', 'names of the other account')
    eq(LogEntry.objects(source='shadow_source').count(), 2, 'log entries')

    body = check('/admin/logentry/', 200).get_data(as_text=True)
    if 'Shadow source big' not in body:
        fail('the log view does not show the entry')
    print('UNKNOWN_HOSTS_OK')


atexit.register(verify)

Host(hostname='known').save()
big = {'id': 'x', 'name': 'big', 'typ': 'csv', 'shadow_mode': True}
small = {'id': 'y', 'name': 'small', 'typ': 'csv', 'shadow_mode': True}
for number in range(5000):
    update_import_host(Host.get_host(f'big-{number}'), {'a': 'b'}, big)
update_import_host(Host.get_host('small-host'), {'a': 'b'}, small)
# A known host is no miss
update_import_host(Host.get_host('known'), {'a': 'b'}, big)
'''


NOTHING_UNKNOWN = LOGIN + '''
import atexit
from application.helpers.import_hostnames import update_import_host
from application.models.host import Host
from application.modules.log.models import LogEntry


def verify():
    """Runs when the process ends, no log entry may have appeared."""
    eq(LogEntry.objects(source='shadow_source').count(), 0, 'log entries')
    print('NOTHING_UNKNOWN_OK')


atexit.register(verify)
Host(hostname='known').save()
update_import_host(Host.get_host('known'), {'a': 'b'},
                   {'id': 'x', 'name': 'big', 'typ': 'csv', 'shadow_mode': True})
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestWebShadowUnknownHosts(unittest.TestCase):
    """The log entry about hosts only a shadow source knows."""

    def _run(self, snippet, marker):
        """A failed check inside atexit only shows by the missing marker."""
        result = run_against_app(snippet, 'False')
        self.assertIn(marker, result.stdout, f"\n{result.stdout[-500:]}\n{result.stderr}")

    def test_unknown_hosts_end_up_in_the_log(self):
        """Exact count, bounded names, one entry per account."""
        self._run(UNKNOWN_HOSTS, 'UNKNOWN_HOSTS_OK')

    def test_no_entry_without_unknown_hosts(self):
        """A source that knows only known hosts leaves no entry behind."""
        self._run(NOTHING_UNKNOWN, 'NOTHING_UNKNOWN_OK')


if __name__ == '__main__':
    unittest.main()
