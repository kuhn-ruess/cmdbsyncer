"""
A host has to survive the whole round trip against the *real* models.

Every other host test in this suite runs against the MagicMock doubles
installed by ``tests/__init__.py``. Those prove that a view or an importer
*calls* ``update_host()`` / ``update_inventory()`` / ``get_export_hosts()``
— never what those methods store, nor which hosts the export selection
hands back. A model that quietly stopped writing labels, or an export
query that started handing out decommissioned hosts, would leave every one
of them green.

So this file walks the three ways a host comes into being — the admin
form, the REST API, and the model methods every importer uses — asserts
what really landed in the database, and finally checks that the export
selection returns exactly the hosts it should.

It runs in the subprocess harness of ``tests/web_smoke_helpers.py``, so the
real ``Host`` document is written to an in-memory mongomock database. See
that module for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


# Creating a host by hand is a CMDB_MODE feature, so this one runs in that
# mode only — with the flag off the form is not offered at all, which
# tests/test_web_requests_smoke.py already covers.
HOST_CREATE_FORM = '''
check('/login', 302, method='post', data={
    'login_email': 'smoke@example.com',
    'password': 'smoke-password',
    'otp': '',
    'login_submit': 'Login',
    'csrf_token': csrf('/login'),
})

from application.models.host import Host

form = '/admin/host/new/'
check(form, 200)
check(form, 302, method='post', data={
    'csrf_token': csrf(form),
    'hostname': ' gui-host.example.com ',
    'source_account_name': 'cmdb',
    'lifecycle_state': 'active',
    'project': '',
    # A full row becomes a label, a row without a value is a deletion and
    # must not be stored as an empty label.
    'cmdb_fields-0-field_name': 'Env Name',
    'cmdb_fields-0-field_value': ' prod ',
    'cmdb_fields-1-field_name': 'dropped',
    'cmdb_fields-1-field_value': '',
})

host = Host.objects(hostname='gui-host.example.com').first()
if not host:
    fail('the host form answered 302 but saved no host')
# The space in the label name is normalised by _fix_key, the value stripped.
eq(host.get_labels(), {'Env_Name': 'prod'}, 'labels of the created host')
eq(host.object_type, 'host', 'object_type of the created host')
eq(host.source_account_id, 'cmdb', 'source account id of the created host')
# A CMDB-managed host is authoritative and must survive every autodelete.
eq(host.no_autodelete, True, 'no_autodelete of the created host')
print('HOST_CREATE_FORM_OK')
'''


# The REST API is the second way in. tests/test_api.py covers auth, scopes
# and payload validation against a mocked Host; this walks the same
# endpoints against the real document and looks at what was persisted.
API_ROUNDTRIP = '''
import base64

from application.models.account import Account
from application.models.host import Host
from application.models.user import User

Account(name='api-account', type='custom', address='https://example.org').save()

api_user = User(email='api@example.com', name='API user',
                api_roles=['all'])
api_user.set_password('api-password')
api_user.save()

AUTH = {'Authorization': 'Basic ' + base64.b64encode(
    b'api@example.com:api-password').decode()}


def api(method, url, payload=None, expected=200):
    """Call the API as the api user; fail unless it answers ``expected``."""
    kwargs = {'headers': AUTH}
    if payload is not None:
        kwargs['json'] = payload
    response = getattr(client, method)('/api/v1' + url, **kwargs)
    if response.status_code != expected:
        fail(f'{method.upper()} {url} answered {response.status_code} '
             f'({response.get_data(as_text=True)[:200]}), expected {expected}')
    return response.get_json()


api('post', '/objects/api-host.example.com',
    {'account': 'api-account', 'labels': {'os': 'linux', 'Env Name': 'prod'}})

host = Host.objects(hostname='api-host.example.com').first()
if not host:
    fail('the API answered 200 but saved no host')
eq(host.get_labels(), {'os': 'linux', 'Env_Name': 'prod'},
   'labels stored by the API')
eq(host.source_account_name, 'api-account', 'account bound by the API')
if not host.last_import_seen:
    fail('the API import did not stamp last_import_seen')

# A second write with the same labels must not claim a sync was needed.
first_sync = host.last_import_sync
api('post', '/objects/api-host.example.com',
    {'account': 'api-account', 'labels': {'os': 'linux', 'Env Name': 'prod'}})
host.reload()
eq(host.last_import_sync, first_sync,
   'last_import_sync after an unchanged API write')

# Inventory goes into its own namespace, prefixed with the section key.
api('post', '/objects/api-host.example.com/inventory',
    {'key': 'checkmk', 'inventory': {'os name': 'Linux', 'cores': 8}})
host.reload()
eq(host.get_inventory('checkmk__'),
   {'checkmk__os_name': 'Linux', 'checkmk__cores': 8},
   'inventory stored by the API')
# Binding the account keeps its own bookkeeping section next to it.
eq(host.get_inventory().get('syncer_account'), 'api-account',
   'the account the syncer bookkeeping records')

# Replacing a section drops the keys the new payload no longer carries.
api('post', '/objects/api-host.example.com/inventory',
    {'key': 'checkmk', 'inventory': {'os name': 'Linux'}})
host.reload()
eq(host.get_inventory('checkmk__'), {'checkmk__os_name': 'Linux'},
   'inventory after a section was replaced')
eq(host.get_inventory().get('syncer_account'), 'api-account',
   'the syncer bookkeeping after a foreign section was replaced')

# What went in has to come back out.
body = api('get', '/objects/api-host.example.com')
eq(body['labels'], {'os': 'linux', 'Env_Name': 'prod'}, 'labels read back')
eq({k: v for k, v in body['inventory'].items() if k.startswith('checkmk__')},
   {'checkmk__os_name': 'Linux'}, 'inventory read back')

# An inventory write must never conjure a host into existence.
api('post', '/objects/ghost.example.com/inventory',
    {'key': 'checkmk', 'inventory': {'cores': 1}}, expected=404)
if Host.objects(hostname='ghost.example.com').first():
    fail('an inventory write created a host')

# Deleting through the API archives the host instead of dropping it.
api('delete', '/objects/api-host.example.com')
host.reload()
if not host.deleted_at:
    fail('the API delete did not soft-delete the host')
eq(host.lifecycle_state, 'archived', 'lifecycle state after the API delete')
print('API_ROUNDTRIP_OK')
'''


# The third way in: the model methods every importer drives. No plugin
# involved — these are the promises update_host() makes to all of them.
IMPORT_LABELS = '''
from application.models.host import Host, HostError

host = Host.get_host('import-host.example.com')
eq(host.source_account_name, None, 'a fresh host has no account yet')

host.update_host({'Os Name': 'linux', 'site': 'muc'})
host.save()
eq(host.get_labels(), {'Os_Name': 'linux', 'site': 'muc'},
   'labels after the first import')
if not host.last_import_sync:
    fail('the first import did not stamp last_import_sync')

# Unchanged data is seen, but not synced: no needless downstream export.
before_sync = host.last_import_sync
host.update_host({'Os Name': 'linux', 'site': 'muc'})
eq(host.last_import_sync, before_sync,
   'last_import_sync after an unchanged import')

# update_host is authoritative: a label missing from the new payload is
# gone, it is not merged with what was there before.
host.update_host({'site': 'ber'})
host.save()
eq(host.get_labels(), {'site': 'ber'}, 'labels after a shrinking import')
if host.last_import_sync == before_sync:
    fail('a changed import did not stamp last_import_sync')

# Same host, asked for again: get_host returns it instead of a second one.
again = Host.get_host('import-host.example.com')
eq(str(again.id), str(host.id), 'get_host on an existing hostname')
eq(Host.objects(hostname='import-host.example.com').count(), 1,
   'documents for one hostname')

# create=False is how importers ask without creating.
if Host.get_host('never-seen.example.com', create=False):
    fail('get_host(create=False) returned a host that does not exist')
if Host.objects(hostname='never-seen.example.com').first():
    fail('get_host(create=False) created a host')

# A source handing over something that is not a hostname has to reach the
# importer as a readable HostError, not as an AttributeError.
for bad in (None, 42, ['host']):
    try:
        Host.get_host(bad)
    except HostError:
        pass
    except Exception as error:
        fail(f'get_host({bad!r}) raised {type(error).__name__}, '
             'expected HostError')
    else:
        fail(f'get_host({bad!r}) did not raise')

# A `$`-prefixed key cannot be stored in Mongo and must be refused before
# the save, not blow up half-written.
try:
    host.update_host({'$evil': 'x'})
except ValueError:
    pass
else:
    fail('update_host accepted a $-prefixed label key')
host.reload()
eq(host.get_labels(), {'site': 'ber'}, 'labels after the rejected import')

# With LABELS_ITERATE_FIRST_LEVEL on, a nested payload is flattened into
# one label per sub-key. The importer keeps using its own dict after the
# call, so the flattening must happen on a copy and leave it untouched.
app.config['LABELS_ITERATE_FIRST_LEVEL'] = True
try:
    nested = Host.get_host('nested-host.example.com')
    incoming = {'net': {'ip': '1.2.3.4', 'mac': 'aa:bb'}, 'site': 'muc'}
    nested.update_host(incoming)
    nested.save()
    eq(nested.get_labels(),
       {'net_ip': '1.2.3.4', 'net_mac': 'aa:bb', 'site': 'muc'},
       'labels after a nested import')
    eq(incoming, {'net': {'ip': '1.2.3.4', 'mac': 'aa:bb'}, 'site': 'muc'},
       'the dict handed to update_host')
finally:
    app.config['LABELS_ITERATE_FIRST_LEVEL'] = False
print('IMPORT_LABELS_OK')
'''


IMPORT_INVENTORY = '''
from application.models.host import Host

host = Host.get_host('inv-host.example.com')
host.update_host({'site': 'muc'})
host.save()

# Every entry is namespaced with the section key, and the key itself runs
# through the same normalisation as a label.
eq(host.update_inventory('checkmk', {'os name': 'Linux', 'cores': 8}), True,
   'update_inventory on new data')
host.save()
eq(host.get_inventory(),
   {'checkmk__os_name': 'Linux', 'checkmk__cores': 8},
   'inventory after the first inventorize run')

# The same data again is not a change — the callers use this to decide
# whether the host needs a sync.
eq(host.update_inventory('checkmk', {'os name': 'Linux', 'cores': 8}), False,
   'update_inventory on unchanged data')

# A second section lives next to the first and must not disturb it.
host.update_inventory('netbox', {'rack': 'r1'})
host.save()
eq(host.get_inventory(),
   {'checkmk__os_name': 'Linux', 'checkmk__cores': 8, 'netbox__rack': 'r1'},
   'inventory with two sections')

# Replacing a section removes what the new payload dropped — and only
# inside that section.
eq(host.update_inventory('checkmk', {'cores': 8}), True,
   'update_inventory on a shrinking section')
host.save()
eq(host.get_inventory(), {'checkmk__cores': 8, 'netbox__rack': 'r1'},
   'inventory after a section shrank')

# get_inventory filters by prefix.
eq(host.get_inventory('netbox'), {'netbox__rack': 'r1'},
   'filtered inventory read')

# An unsafe key is refused instead of being written.
try:
    host.update_inventory('checkmk', {'$evil': 'x'})
except ValueError:
    pass
else:
    fail('update_inventory accepted a $-prefixed key')

# set_inventory_attribute saves itself, and only when something changed.
eq(host.set_inventory_attribute('single', 'first'), True,
   'set_inventory_attribute on a new key')
eq(host.set_inventory_attribute('single', 'first'), False,
   'set_inventory_attribute on an unchanged value')
eq(host.set_inventory_attribute('single', 'second'), True,
   'set_inventory_attribute on a changed value')
host.reload()
eq(host.get_inventory().get('single'), 'second',
   'the attribute set_inventory_attribute persisted')
print('IMPORT_INVENTORY_OK')
'''


# What the syncers ask for before they talk to a target system. Every
# consumer test mocks these away, so this is the only place the queries
# themselves run.
EXPORT_SELECTION = '''
from application.models.host import Host

def make(hostname, **fields):
    host = Host.get_host(hostname)
    host.update_host({'site': 'muc'})
    for key, value in fields.items():
        setattr(host, key, value)
    host.save()
    return host

active = make('export-active.example.com')
planned = make('export-planned.example.com', lifecycle_state='planned')
decom = make('export-decom.example.com', lifecycle_state='decommissioned')
template = make('export-template.example.com', object_type='template')
an_object = make('export-object.example.com', is_object=True,
                 object_type='service')

archived = make('export-archived.example.com')
archived.soft_delete(reason='manual test')
archived.save()


def names(queryset):
    return sorted(host.hostname for host in queryset)


# Templates are normal hosts as far as the host export is concerned; only
# Objects are held back there. A soft-deleted host is out in either mode.
expected_hosts = [
    'export-active.example.com',
    'export-planned.example.com',
    'export-decom.example.com',
    'export-template.example.com',
]
if CMDB_MODE:
    # In CMDB mode the lifecycle decides: nothing but 'active' is exported.
    expected_hosts = ['export-active.example.com',
                      'export-template.example.com']
eq(names(Host.get_export_hosts()), sorted(expected_hosts),
   'hosts offered to the export')

# active_non_template() adds the Objects and drops the templates.
expected_fleet = [
    'export-active.example.com',
    'export-planned.example.com',
    'export-decom.example.com',
    'export-object.example.com',
]
if CMDB_MODE:
    expected_fleet = ['export-active.example.com',
                      'export-object.example.com']
eq(names(Host.active_non_template()), sorted(expected_fleet),
   'the active fleet')

# objects_by_filter() without a filter is the host slice again; with one
# it selects by object_type.
eq(names(Host.objects_by_filter([])), sorted(expected_hosts),
   'objects_by_filter without a filter')
eq(names(Host.objects_by_filter(['service'])), ['export-object.example.com'],
   'objects_by_filter on an object type')

# A restored host comes back into the export.
archived.restore('active')
archived.save()
if 'export-archived.example.com' not in names(Host.get_export_hosts()):
    fail('a restored host is still missing from the export')
print('EXPORT_SELECTION_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestHostRoundtripSmoke(unittest.TestCase):
    """Create hosts the three real ways, then export them again."""

    def _run_mode(self, snippet, marker, cmdb_mode):
        """Run `snippet` in one CMDB mode; assert it succeeds."""
        result = run_against_app(snippet, cmdb_mode)
        self.assertEqual(
            result.returncode, 0,
            f"CMDB_MODE={cmdb_mode}:\n{result.stdout}\n{result.stderr}")
        self.assertIn(marker, result.stdout)

    def _run(self, snippet, marker):
        """Run `snippet` for both CMDB_MODE values; assert both succeed."""
        for cmdb_mode in ('False', 'True'):
            with self.subTest(cmdb_mode=cmdb_mode):
                self._run_mode(snippet, marker, cmdb_mode)

    def test_host_form_saves_what_it_was_given(self):
        """The admin form really writes a host, with its labels."""
        self._run_mode(HOST_CREATE_FORM, 'HOST_CREATE_FORM_OK', 'True')

    def test_api_stores_and_returns_the_host(self):
        """Labels and inventory posted to the API survive and come back."""
        self._run(API_ROUNDTRIP, 'API_ROUNDTRIP_OK')

    def test_import_stores_labels(self):
        """update_host keeps the promises every importer relies on."""
        self._run(IMPORT_LABELS, 'IMPORT_LABELS_OK')

    def test_import_manages_inventory(self):
        """Inventory sections stay namespaced, and separate from each other."""
        self._run(IMPORT_INVENTORY, 'IMPORT_INVENTORY_OK')

    def test_export_selects_the_right_hosts(self):
        """Only hosts that may leave the syncer reach a target system."""
        self._run(EXPORT_SELECTION, 'EXPORT_SELECTION_OK')


if __name__ == '__main__':
    unittest.main()
