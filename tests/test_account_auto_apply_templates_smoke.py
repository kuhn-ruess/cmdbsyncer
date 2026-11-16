"""
Auto Apply Templates of an account: every object imported through the
account gets those CMDB templates, a child account without own ones
applies the templates of its parent, and the form offers templates only.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application.helpers.get_account import get_account_by_name
from application.models.account import Account
from application.models.host import Host

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})

tpl_a = Host(hostname='tpl-a', object_type='template', is_object=True)
tpl_a.save()
tpl_b = Host(hostname='tpl-b', object_type='template', is_object=True)
tpl_b.save()
other = Host(hostname='srv01')
other.save()

parent = Account(name='objects', type='csv', is_object=True, object_type='location',
                 enabled=True, auto_apply_templates=[tpl_a])
parent.save()
child = Account(name='objects-child', is_child=True, parent=parent, enabled=True)
child.save()

# A new object gets the template, a manual one stays
obj = Host(hostname='site7')
obj.cmdb_templates = [tpl_b]
eq(obj.set_account(get_account_by_name('objects')), True, 'import accepted')
obj.save()
obj.reload()
eq([t.id for t in obj.cmdb_templates], [tpl_b.id, tpl_a.id], 'templates of the object')

# A second import changes nothing
eq(obj.set_account(get_account_by_name('objects')), True, 'second import accepted')
eq(len(obj.cmdb_templates), 2, 'templates after the second import')

# The child account applies the templates of its parent
child_obj = Host(hostname='site8')
child_obj.set_account(get_account_by_name('objects-child'))
eq([t.id for t in child_obj.cmdb_templates], [tpl_a.id], 'templates via child account')

# The form offers the templates, no ordinary host
body = check(f'/admin/account/edit/?id={parent.id}', 200).get_data(as_text=True)
eq('tpl-b' in body, True, 'template offered')
eq('srv01' in body, False, 'host offered')
body = check(f'/admin/account_childs/edit/?id={child.id}', 200).get_data(as_text=True)
eq('tpl-b' in body, True, 'template offered to the child account')

print('AUTO_APPLY_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class AccountAutoApplyTemplatesTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_auto_apply_templates(self):
        """Imported objects get the templates of their account."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('AUTO_APPLY_OK', result.stdout)
