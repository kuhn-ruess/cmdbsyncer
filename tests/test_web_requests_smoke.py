"""
The web application must serve its pages, not just import.

``tests/test_web_boot_smoke.py`` proves the app starts. These tests go one
step further and walk the paths an operator actually uses — log in, open the
host and object lists, create an account through its two-step form, save a
rule — and assert that the objects really land in the database.

Everything runs twice, with ``CMDB_MODE`` off and on: the flag decides how
the host and object views are built, so a change that breaks one variant
usually leaves the other intact. The default is off, which is the variant
nobody develops against.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


LOGIN = '''
check('/login', 200)
check('/login', 302, method='post', data={
    'login_email': 'smoke@example.com',
    'password': 'smoke-password',
    'otp': '',
    'login_submit': 'Login',
    'csrf_token': csrf('/login'),
})
'''

LIST_PAGES = LOGIN + '''
check('/admin/host/', 200)
check('/admin/Objects/', 200)
check('/admin/account/', 200)
check('/admin/archive/', 200)
check('/admin/checkmkfilterrule/', 200)
print('LIST_PAGES_OK')
'''

CREATE_ACCOUNT = LOGIN + '''
from application.models.account import Account

form = '/admin/account/new/?type=custom'
check('/admin/account/new/', 200)
check(form, 200)
check(form, 302, method='post', data={
    'csrf_token': csrf(form),
    'name': 'smoke-account',
    'typ': 'custom',
    'address': 'https://example.org',
})
found = Account.objects(name='smoke-account').count()
if found != 1:
    fail(f'the account form answered 302 but saved {found} accounts')
print('CREATE_ACCOUNT_OK')
'''

CREATE_RULE = LOGIN + '''
from application.plugins.checkmk.models import CheckmkFilterRule

form = '/admin/checkmkfilterrule/new/'
check(form, 200)
check(form, 302, method='post', data={
    'csrf_token': csrf(form),
    'name': 'smoke-rule',
    'condition_typ': 'anyway',
    'sort_field': '0',
    'enabled': 'y',
})
found = CheckmkFilterRule.objects(name='smoke-rule').count()
if found != 1:
    fail(f'the rule form answered 302 but saved {found} rules')
print('CREATE_RULE_OK')
'''

# A lookup table is saved from its form, a table that cannot be read is
# refused, a rendered template reads the saved one and the Jinja help of
# the rule forms lists it.
CREATE_LOOKUP_TABLE = LOGIN + '''
from application.models.lookup_table import LookupTable
from application.helpers.syncer_jinja import render_jinja

form = '/admin/lookuptable/new/'
check(form, 200)
check(form, 200, method='post', data={
    'csrf_token': csrf(form),
    'name': 'smoke-broken',
    'entries': 'location;datacenter\\nsite-a;DC1\\nsite-a;DC2',
})
if LookupTable.objects(name='smoke-broken').count():
    fail('a table with a duplicate key was saved')
check(form, 302, method='post', data={
    'csrf_token': csrf(form),
    'name': 'smoke-lookup',
    'entries': 'location;datacenter\\nsite-a;DC1\\nsite-b;DC2',
})
if LookupTable.objects(name='smoke-lookup').count() != 1:
    fail('the lookup table form answered 302 but saved nothing')
listing = check('/admin/lookuptable/', 200).get_data(as_text=True)
if '2 keys' not in listing:
    fail('the list does not show the size of the table')
eq(render_jinja("{{ lookup('smoke-lookup', location) }}", location='site-b'),
   'DC2', 'the rendered lookup')
# The Jinja help of the rule forms offers the saved table.
page = check('/admin/customattributerule/new/', 200).get_data(as_text=True)
if 'jinja-help-btn' not in page or 'smoke-lookup' not in page:
    fail('the custom attribute form has no Jinja help with the lookup table')
page = check('/admin/checkmkrewriteattributerule/new/', 200).get_data(as_text=True)
if 'jinja-help-btn' not in page:
    fail('the rewrite attribute form has no Jinja help')
print('CREATE_LOOKUP_TABLE_OK')
'''

# The Setup Rule form: Jinja help next to Value Template and Folder (with
# HOST_FOLDER), the key/value editor of the label conditions and its
# suggestions, and HOST_FOLDER refused where there is no host.
SETUP_RULE_FORM = LOGIN + '''
from application.models.host import Host
from application.plugins.checkmk.models import CheckmkRuleMngmt, RuleMngmtOutcome

base = '/admin/checkmkrulemngmt'
page = check(f'{base}/new/', 200).get_data(as_text=True)
for needle in ('jinja-help-btn', 'HOST_FOLDER', 'label-cond-endpoint',
               '_label_suggestions'):
    if needle not in page:
        fail(f'the Setup Rule form does not show {needle!r}')

host = Host.get_host('smoke-label-host')
host.update_host({'os': 'linux'})
host.save()
CheckmkRuleMngmt(
    name='smoke-labels', enabled=True, condition_typ='anyway',
    outcomes=[RuleMngmtOutcome(ruleset='r', folder='/', value_template='1',
                               condition_label_template='os:windows',
                               condition_service_label='team:web')]).save()
eq(check(f'{base}/_label_suggestions?kind=host', 200).get_json()['suggestions'],
   ['os'], 'host label keys')
eq(check(f'{base}/_label_suggestions?kind=host&key=os', 200).get_json()['suggestions'],
   ['linux', 'windows'], 'host label values')
eq(check(f'{base}/_label_suggestions?kind=service', 200).get_json()['suggestions'],
   ['team'], 'service label keys')

def post(name, expected, rule_source, list_source=''):
    form = f'{base}/new/'
    return check(form, expected, method='post', data={
        'csrf_token': csrf(form),
        'name': name,
        'condition_typ': 'anyway',
        'rule_source': rule_source,
        'list_source': list_source,
        'enabled': 'y',
        'outcomes-0-ruleset': 'checkgroup_parameters:filesystem',
        'outcomes-0-folder': '{{ HOST_FOLDER }}',
        'outcomes-0-folder_index': '0',
        'outcomes-0-value_template': '{}',
    })

answer = post('smoke-folder-list', 200, 'list', 'service\\nDisk C:\\n')
if CheckmkRuleMngmt.objects(name='smoke-folder-list').count():
    fail('a list rule with HOST_FOLDER was saved')
if 'needs a host' not in answer.get_data(as_text=True):
    fail('the refused list rule does not say why')
post('smoke-folder-host', 302, 'hosts')
if CheckmkRuleMngmt.objects(name='smoke-folder-host').count() != 1:
    fail('a per host rule with HOST_FOLDER was not saved')
print('SETUP_RULE_FORM_OK')
'''

# Creating hosts by hand is a CMDB_MODE feature. With the flag off the two
# views must send the user away instead of offering the form — that is the
# behaviour the can_create/can_edit properties carry, and getting it wrong
# is what took the whole web application down in 4.3.0 and 4.3.1.
HOST_CREATE_GATE = LOGIN + '''
expected = 200 if CMDB_MODE else 302
check('/admin/host/new/', expected)
check('/admin/Objects/new/', expected)
print('HOST_CREATE_GATE_OK')
'''


# The preview runs the whole generation with the writing left out. A rule
# without an LDAP account asks no directory, so the full path — host
# attributes, group selection, rendered user fields, rendered table — runs
# here without a server to talk to.
USER_GENERATION_PREVIEW = LOGIN + '''
from application.models.host import Host
from application.plugins.checkmk.user_models import (
    CheckmkUserGenerationRule,
    CmkUserGenerationOutcome,
)

page = '/admin/checkmk_user_generation_preview/'
check(page, 200)
# Nothing configured yet: the page says so instead of breaking
check(page + '?preview=1', 200)

host = Host.get_host('smoke-host')
host.update_host({'ldap_group': 'grp-dba'})
host.save()

rule = CheckmkUserGenerationRule(name='smoke-generation', enabled=True)
rule.outcome = CmkUserGenerationOutcome(
    foreach_type='label',
    foreach='ldap_group',
    rewrite_group_name='{{name}}',
    rewrite_user_id='{{name}}',
    rewrite_full_name='{{name}}',
    roles=['user'],
    contact_groups=['cg_{{name}}'],
)
rule.save()

body = check(page + '?preview=1', 200).get_data(as_text=True)
for needle in ('grp-dba', 'new in Checkmk', 'cg_grp-dba',
               # email and pager are shown even when their template is
               # empty, and the run's own bookkeeping is not an error
               'pager_address', 'stays empty'):
    if needle not in body:
        fail(f'the preview page does not show {needle!r}')
if 'started' in body:
    fail('the preview page shows the run bookkeeping as an error')
# A wide table scrolls in its own container, and its sticky header has to
# stick to that container instead of 60px into it, on top of the first row
if 'table-scroll' not in body:
    fail('the result table is not in its own scroll container')
if 'style="overflow-x: auto;"' in body:
    fail('the result table still carries the inline overflow that breaks sticky')

# The rule list carries the link to it
listing = check('/admin/checkmkusergenerationrule/', 200).get_data(as_text=True)
if 'checkmk_user_generation_preview' not in listing:
    fail('the rule list does not link the preview')
print('USER_GENERATION_PREVIEW_OK')
'''


# The Checkmk Folders page and the debug of a folder, calculated from the
# real rules: two hosts share a folder and each gives its contact group.
# Nothing is saved, and a user with an account scope sees only their part.
CHECKMK_FOLDERS = LOGIN + '''
from application.models.host import Host
from application.models.user import User
from application.plugins.checkmk.models import CheckmkRule, CheckmkRuleOutcome

for name, team, source in (('folder-host-a', 'team_a', 'source_a'),
                           ('folder-host-b', 'team_b', 'source_b')):
    host = Host.get_host(name)
    host.update_host({'team': team})
    host.source_account_name = source
    host.save()
CheckmkRule(name='smoke-folder-rule', enabled=True, condition_typ='anyway',
            outcomes=[CheckmkRuleOutcome(
                action='move_folder',
                action_param="shared|{'contactgroups': "
                             "{'groups': ['{{ team }}'], 'use': True}}")]).save()
before = {h.hostname: (h.cache, h.folder) for h in Host.objects()}

base = '/admin/checkmk_folders'
check(f'{base}/', 200)
page = check(f'{base}/?calculate=1', 200).get_data(as_text=True)
for needle in ('/shared', 'team_a', 'team_b', 'folder-host-b'):
    if needle not in page:
        fail(f'the folder list does not show {needle!r}')
page = check(f'{base}/debug?folder=/shared', 200).get_data(as_text=True)
for needle in ('smoke-folder-rule', 'added to the list', 'contactgroups.groups',
               'folder-host-a', 'folder-host-b'):
    if needle not in page:
        fail(f'the folder debug does not show {needle!r}')
after = {h.hostname: (h.cache, h.folder) for h in Host.objects()}
eq(after, before, 'hosts after the calculation')

user = User.objects.get(email='smoke@example.com')
user.restrict_to_accounts = ['source_a']
user.save()
page = check(f'{base}/?calculate=1', 200).get_data(as_text=True)
if 'team_a' not in page:
    fail('a scoped user does not see their contact group')
for needle in ('team_b', 'folder-host-b'):
    if needle in page:
        fail(f'a scoped user sees {needle!r} of a host outside their scope')
page = check(f'{base}/debug?folder=/shared', 200).get_data(as_text=True)
if 'team_b' in page or 'outside' not in page:
    fail('the scoped folder debug leaks or does not say what it leaves out')
print('CHECKMK_FOLDERS_OK')
'''

@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestWebRequestsSmoke(unittest.TestCase):
    """Walk the real request paths in both CMDB modes."""

    def _run(self, snippet, marker):
        """Run `snippet` for both CMDB_MODE values; assert both succeed."""
        for cmdb_mode in ('False', 'True'):
            with self.subTest(cmdb_mode=cmdb_mode):
                result = run_against_app(snippet, cmdb_mode)
                self.assertEqual(
                    result.returncode, 0,
                    f"CMDB_MODE={cmdb_mode}:\n{result.stdout}\n{result.stderr}")
                self.assertIn(marker, result.stdout)

    def test_list_pages_render(self):
        """Login, then the lists an operator opens every day."""
        self._run(LIST_PAGES, 'LIST_PAGES_OK')

    def test_account_can_be_created(self):
        """The two-step account form saves what it was given."""
        self._run(CREATE_ACCOUNT, 'CREATE_ACCOUNT_OK')

    def test_rule_can_be_created(self):
        """A rule form saves what it was given."""
        self._run(CREATE_RULE, 'CREATE_RULE_OK')

    def test_lookup_table_can_be_created(self):
        """A lookup table form saves a valid table and refuses a broken one."""
        self._run(CREATE_LOOKUP_TABLE, 'CREATE_LOOKUP_TABLE_OK')

    def test_setup_rule_form_helpers(self):
        """Jinja help, label editor and HOST_FOLDER of the Setup Rule form."""
        self._run(SETUP_RULE_FORM, 'SETUP_RULE_FORM_OK')

    def test_host_create_follows_cmdb_mode(self):
        """Hand-made hosts are offered in CMDB mode and only there."""
        self._run(HOST_CREATE_GATE, 'HOST_CREATE_GATE_OK')

    def test_checkmk_folders(self):
        """Folder list and folder debug, read only and scoped."""
        self._run(CHECKMK_FOLDERS, 'CHECKMK_FOLDERS_OK')

    def test_user_generation_preview_renders(self):
        """The preview shows what a generation run would create."""
        self._run(USER_GENERATION_PREVIEW, 'USER_GENERATION_PREVIEW_OK')


if __name__ == '__main__':
    unittest.main()
