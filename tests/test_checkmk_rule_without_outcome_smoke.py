"""
A Checkmk group or user generation rule may lack its outcome: the field isn't
required and a rule import can leave it out. Such a rule must neither take
down its list nor the export.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application.plugins.checkmk.groups import rules_with_outcome as group_rules
from application.plugins.checkmk.models import CheckmkGroupRule
from application.plugins.checkmk.user_generation import \\
    rules_with_outcome as user_generation_rules
from application.plugins.checkmk.user_models import CheckmkUserGenerationRule

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})

for model, url, rules in (
        (CheckmkGroupRule, '/admin/checkmkgrouprule/', group_rules),
        (CheckmkUserGenerationRule, '/admin/checkmkusergenerationrule/',
         user_generation_rules)):
    model(name='no-outcome', enabled=True).save()
    body = check(url, 200).get_data(as_text=True)
    if 'no-outcome' not in body:
        fail(f'{url} does not list the rule')
    eq(list(rules()), [], f'enabled rules with an outcome of {model.__name__}')

print('NO_OUTCOME_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class RuleWithoutOutcomeTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_rule_without_outcome(self):
        """The list renders and the export leaves the rule out."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('NO_OUTCOME_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
