"""
The Checkmk debug page shows what the export sends: a rule's template is
rendered once, and a Jinja expression inside an attribute value stays text.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application.models.account import Account
from application.models.host import Host
from application.plugins.checkmk import get_host_debug_data
from application.plugins.checkmk.models import CheckmkRule

account = Account(name='target', type='csv', address='example.com', username='u')
account.set_password('account-secret')
account.save()

host = Host(hostname='srv01', source_account_name='x')
host.labels = {'plain': 'prod',
               'math': '{{ 7 * 7 }}',
               'macro': '{{ACCOUNT:target:password}}'}
host.save()

CheckmkRule(
    name='labels', condition_typ='anyway', enabled=True, sort_field=1,
    outcomes=[{'action': 'prefix_labels', 'action_param': '{{ plain }}/'},
              {'action': 'dont_update_prefixed_labels', 'action_param': '{{ math }}'},
              {'action': 'dont_update_prefixed_labels', 'action_param': '{{ macro }}'}],
).save()

with app.test_request_context():
    _attributes, actions, _log = get_host_debug_data('srv01')

# --- the template of the rule is rendered
eq(actions['label_prefix'], 'prod/', 'template of the rule')

# --- what comes out of an attribute stays what it is
values = actions['dont_update_prefixed_labels']
eq('{{ 7 * 7 }}' in values, True, f'attribute value evaluated: {values}')
eq('{{ACCOUNT:target:password}}' in values, True, f'macro in an attribute resolved: {values}')
eq('account-secret' in str(actions), False, 'account password on the debug page')

print('DEBUG_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CheckmkDebugRerenderTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_no_second_render(self):
        """An attribute value is not evaluated as a template."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('DEBUG_OK', result.stdout)
