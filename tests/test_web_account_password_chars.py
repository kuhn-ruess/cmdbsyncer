"""
A password may hold any character a target system accepts.

Backslashes, quotes, braces, percent and dollar signs and non ASCII
letters are common in generated passwords. Saving one through the account
form must store it unchanged, and an {{ACCOUNT:<name>:password}} macro
must hand it on exactly as typed. A value typed straight into an Ansible
custom variable must reach the inventory the same way.

Runs against the real app like ``tests/test_web_requests_smoke.py``, see
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = LOGIN + r'''
from application.models.account import Account
from application.helpers.syncer_jinja import render_jinja

PASSWORDS = [
    'back\\slash\\',
    "single'quote",
    'double"quote',
    'br{ace}s{{x}}',
    '{% if %}',
    '{#c#}',
    'per%cent%s',
    'dol$lar$1',
    'ünïcödé€',
    'all\\\'"{}%$ü',
]

form = '/admin/account/new/?type=custom'
check(form, 200)
check(form, 302, method='post', data={
    'csrf_token': csrf(form),
    'name': 'chars-account',
    'typ': 'custom',
    'address': 'https://example.org',
    'enabled': 'y',
    'password': PASSWORDS[0],
})
account = Account.objects.get(name='chars-account')
eq(account.get_password(), PASSWORDS[0], 'password after create')

edit = f'/admin/account/edit/?id={account.pk}'
for number, password in enumerate(PASSWORDS):
    check(edit, 302, method='post', data={
        'csrf_token': csrf(edit),
        'name': 'chars-account',
        'address': 'https://example.org',
        'enabled': 'y',
        'password': password,
    })
    account = Account.objects.get(name='chars-account')
    eq(account.get_password(), password, f'password {number} after edit')
    eq(render_jinja('{{ACCOUNT:chars-account:password}}'), password,
       f'password {number} through the macro')
    eq(render_jinja('pre-{{ ACCOUNT:chars-account:password }}-post',
                    mode='nullify'),
       f'pre-{password}-post', f'password {number} inside a template')
print('PASSWORD_CHARS_OK')
'''

ANSIBLE_VARIABLE = LOGIN + r'''
import json
from application.models.host import Host
from application.models.user import User
from application.modules.inventory import render_ansible_inventory
from application.plugins.ansible.models import (AnsibleCustomVariablesRule,
                                                ensure_default_project)

VALUE = 'a\\b"c\'d{e}%f$g ü€'
ensure_default_project()
host = Host.get_host('srv01')
host.update_host({'os': 'linux'})
host.save()

form = '/admin/ansiblecustomvariablesrule/new/'
check(form, 200)
check(form, 302, method='post', data={
    'csrf_token': csrf(form),
    'name': 'chars-rule',
    'condition_typ': 'anyway',
    'sort_field': '0',
    'enabled': 'y',
    'outcomes-0-attribute_name': 'secret',
    'outcomes-0-attribute_value': VALUE,
})
rule = AnsibleCustomVariablesRule.objects.get(name='chars-rule')
eq(rule.outcomes[0].attribute_value, VALUE, 'value stored by the rule form')
eq(render_ansible_inventory('ansible', host='srv01')['secret'], VALUE,
   'value in the inventory')

api_user = User(email='api@example.com', name='api', api_roles=['all'])
api_user.set_password('api-password')
api_user.save()
response = check('/api/v1/ansible/inventory/ansible?host=srv01', 200,
                 headers={'x-login-user': 'api@example.com:api-password'})
eq(json.loads(response.get_data(as_text=True))['secret'], VALUE,
   'value in the inventory API answer')
print('ANSIBLE_VARIABLE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestAccountPasswordChars(unittest.TestCase):
    """Special characters in an account password survive save and render."""

    def _run(self, snippet, marker):
        """Run `snippet` for both CMDB_MODE values; assert both succeed."""
        for cmdb_mode in ('False', 'True'):
            with self.subTest(cmdb_mode=cmdb_mode):
                result = run_against_app(snippet, cmdb_mode)
                self.assertEqual(
                    result.returncode, 0,
                    f"CMDB_MODE={cmdb_mode}:\n{result.stdout}\n{result.stderr}")
                self.assertIn(marker, result.stdout)

    def test_special_characters_round_trip(self):
        """Every password comes back from storage and the macro unchanged."""
        self._run(SNIPPET, 'PASSWORD_CHARS_OK')

    def test_ansible_variable_reaches_the_inventory(self):
        """A typed in Ansible variable is not escaped on its way out."""
        self._run(ANSIBLE_VARIABLE, 'ANSIBLE_VARIABLE_OK')


if __name__ == '__main__':
    unittest.main()
