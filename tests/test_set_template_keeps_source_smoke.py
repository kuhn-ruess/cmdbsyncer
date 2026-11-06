"""
The bulk action Set Template adds a template. It must not take an imported
host away from its source, which would make every later import skip it.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from datetime import datetime

from application.models.account import CMDB_SOURCE_ACCOUNT_ID, CMDB_SOURCE_ACCOUNT_NAME
from application.models.host import Host

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})

SEEN = datetime(2020, 1, 2, 3, 4, 5)
ACCOUNT = {'id': 'acc1', 'name': 'source', 'typ': 'csv'}

template = Host(hostname='tpl', object_type='template', is_object=True)
template.save()

imported = Host(hostname='imported', source_account_id='acc1', source_account_name='source',
                last_import_seen=SEEN, last_import_sync=SEEN,
                cache={'checkmk_hostattribute': {'attributes': {}}})
imported.save()
native = Host(hostname='native', source_account_id=CMDB_SOURCE_ACCOUNT_ID,
              source_account_name=CMDB_SOURCE_ACCOUNT_NAME, cache={'old': {}})
native.save()

ids = f'{imported.id},{native.id}'
base = '/admin/host/'
token = csrf(f'{base}set_template_form?ids={ids}')
check(f'{base}process_template_assignment', 302, method='post', data={
    'host_ids': ids, 'template_id': str(template.id), 'csrf_token': token})

imported.reload()
eq([entry.id for entry in imported.cmdb_templates], [template.id], 'template of the host')
eq(imported.cache, {}, 'cache of the host')
eq(imported.source_account_id, 'acc1', 'source account id')
eq(imported.source_account_name, 'source', 'source account name')
eq(imported.last_import_seen, SEEN, 'last seen')
eq(imported.last_import_sync, SEEN, 'last sync')
eq(imported.set_account(ACCOUNT), True, 'the next import may update the host')

native.reload()
eq(native.cache, {}, 'cache of the CMDB host')
eq(native.source_account_id, CMDB_SOURCE_ACCOUNT_ID, 'account of the CMDB host')
eq(native.set_account(ACCOUNT), False, 'the CMDB host stays locked')

print('SET_TEMPLATE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class SetTemplateKeepsSourceTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_set_template(self):
        """The template is added, the host stays with its source."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('SET_TEMPLATE_OK', result.stdout)
