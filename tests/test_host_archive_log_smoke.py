"""
Archiving a host and bringing it back is written to the log of the host:
the UI delete, the archive after an import that missed the host, and the
restore, by hand or by the next import.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application.models.host import Host

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})


def last_log(host):
    """The newest log line of the host, without its time"""
    host.reload()
    return host.log[0].split(' ', 2)[-1] if host.log else None


# Deleted in the host list, restored in the archive
ui_host = Host(hostname='srv01', log=['2020-01-01 older entry'])
ui_host.save()
check('/admin/host/delete/', 302, method='post', data={
    'id': str(ui_host.id), 'csrf_token': csrf('/admin/host/')})
eq(last_log(ui_host), 'Soft-deleted (deleted via UI by smoke@example.com)', 'UI delete')
check(f'/admin/archive/restore_row?id={ui_host.id}', 302)
eq(last_log(ui_host), 'Restored to active (restored via UI by smoke@example.com)',
   'UI restore')
eq(ui_host.log[-1], '2020-01-01 older entry', 'older entries kept')

# Missed by an import, back with the next one
imp_host = Host(hostname='srv02', source_account_id='acc1',
                source_account_name='source', last_import_id='old')
imp_host.save()
eq(Host.delete_host_not_found_on_import('source', 'new'), 1, 'archived by import')
eq(last_log(imp_host), 'Soft-deleted (not seen on import)', 'import archive')
imp_host.set_import_seen()
imp_host.save()
eq(last_log(imp_host), 'Restored to active (seen on import again)', 'import restore')

print('ARCHIVE_LOG_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class HostArchiveLogTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_archive_log(self):
        """Archive and restore show up in the host log."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('ARCHIVE_LOG_OK', result.stdout)
