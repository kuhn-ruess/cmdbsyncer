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

# The rule list carries the link to it
listing = check('/admin/checkmkusergenerationrule/', 200).get_data(as_text=True)
if 'checkmk_user_generation_preview' not in listing:
    fail('the rule list does not link the preview')
print('USER_GENERATION_PREVIEW_OK')
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

    def test_host_create_follows_cmdb_mode(self):
        """Hand-made hosts are offered in CMDB mode and only there."""
        self._run(HOST_CREATE_GATE, 'HOST_CREATE_GATE_OK')

    def test_user_generation_preview_renders(self):
        """The preview shows what a generation run would create."""
        self._run(USER_GENERATION_PREVIEW, 'USER_GENERATION_PREVIEW_OK')


if __name__ == '__main__':
    unittest.main()
