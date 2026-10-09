"""
An {{ACCOUNT:<name>:<field>}} macro in an Ansible custom variable must
reach the inventory with the account's current value.

The inventory is served from the per host outcome cache, which holds the
macro already resolved. Two ways left a wrong value in there: the host
debug page, which renders with masked secrets, and an account created or
changed after the cache was built.

Runs against the real app like ``tests/test_web_requests_smoke.py``, see
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SETUP = LOGIN + '''
from application.models.account import Account
from application.models.host import Host
from application.modules.inventory import render_ansible_inventory
from application.modules.rule.models import CustomAttribute
from application.plugins.ansible.models import (AnsibleCustomVariablesRule,
                                                ensure_default_project)

ensure_default_project()
AnsibleCustomVariablesRule(name='smoke-account-vars', enabled=True,
                           condition_typ='anyway', outcomes=[
    CustomAttribute(attribute_name='cmk_secret',
                    attribute_value='{{ACCOUNT:mon:password}}'),
    CustomAttribute(attribute_name='cmk_user',
                    attribute_value='{{ACCOUNT:mon:username}}'),
]).save()
host = Host.get_host('srv01')
host.update_host({'os': 'linux'})
host.save()


def make_account():
    """The account the rule reads from."""
    account = Account(name='mon', type='cmkv2', enabled=True,
                      address='https://cmk.example.com', username='automation')
    account.save()
    account.set_password('s3cret-pw')
    return account


def inventory():
    """The inventory variables of srv01."""
    return render_ansible_inventory('ansible', host='srv01')
'''

DEBUG_PAGE = SETUP + '''
make_account()
expected = {'cmk_secret': 's3cret-pw', 'cmk_user': 'automation'}
eq(inventory(), expected, 'inventory before the debug page')
body = check('/admin/host/debug?hostname=srv01&mode=ansible_host',
             200).get_data(as_text=True)
if 's3cret-pw' in body:
    fail('the debug page shows the account password')
# The debug run masks the secret; that masked outcome must not end up in
# the cache the inventory is served from.
eq(inventory(), expected, 'inventory after the debug page')
print('DEBUG_PAGE_OK')
'''

ACCOUNT_CHANGE = SETUP + '''
eq(inventory(), {'cmk_secret': '', 'cmk_user': ''},
   'inventory without the account')
account = make_account()
eq(inventory(), {'cmk_secret': 's3cret-pw', 'cmk_user': 'automation'},
   'inventory after the account was created')
account.username = 'deploy'
account.save()
eq(inventory(), {'cmk_secret': 's3cret-pw', 'cmk_user': 'deploy'},
   'inventory after the account was changed')
print('ACCOUNT_CHANGE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestAnsibleAccountInventory(unittest.TestCase):
    """Account macros in the Ansible inventory, in both CMDB modes."""

    def _run(self, snippet, marker):
        """Run `snippet` for both CMDB_MODE values; assert both succeed."""
        for cmdb_mode in ('False', 'True'):
            with self.subTest(cmdb_mode=cmdb_mode):
                result = run_against_app(snippet, cmdb_mode)
                self.assertEqual(
                    result.returncode, 0,
                    f"CMDB_MODE={cmdb_mode}:\n{result.stdout}\n{result.stderr}")
                self.assertIn(marker, result.stdout)

    def test_debug_page_keeps_the_secret_in_the_inventory(self):
        """The masked secret of the debug page never reaches the inventory."""
        self._run(DEBUG_PAGE, 'DEBUG_PAGE_OK')

    def test_account_change_reaches_the_inventory(self):
        """A created or changed account is used without a cache rebuild."""
        self._run(ACCOUNT_CHANGE, 'ACCOUNT_CHANGE_OK')


if __name__ == '__main__':
    unittest.main()
