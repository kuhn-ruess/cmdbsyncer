"""
FIRST_MATCHING_TAG and FIRST_MATCHING_VALUE in the Jinja templates of Custom
Attribute and Rewrite rules, rendered for real.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from unittest.mock import Mock

from application.modules.custom_attributes.rules import CustomAttributeRule
from application.modules.rule.rewrite import Rewrite

TEMPLATE = '{{ FIRST_MATCHING_TAG }}={{ FIRST_MATCHING_VALUE }}/{{ FIST_MATCHING_VALUE }}'


def condition(tag, value, tag_match='equal'):
    return {'match_type': 'tag', 'tag': tag, 'tag_match': tag_match,
            'tag_match_negate': False, 'value': value, 'value_match': 'equal',
            'value_match_negate': False}


def rule(name, conditions, outcome, typ='all'):
    doc = Mock()
    doc.to_mongo.return_value = {
        'name': name, '_id': name, 'condition_typ': typ, 'conditions': conditions,
        'outcomes': [outcome], 'last_match': False,
    }
    return doc


def custom(name, conditions, typ='all'):
    return rule(name, conditions,
                {'attribute_name': name, 'attribute_value': TEMPLATE}, typ)


def run(engine, rules):
    engine.rules = rules
    engine.attributes = {'site': 'ber', 'role': 'web'}
    return engine.check_rules('host-a')


# The fast lookup of an equal tag, and the loop over the attributes
result = run(CustomAttributeRule(), [
    custom('fast', [condition('site', 'ber')]),
    custom('loop', [condition('rol', 'web', tag_match='in')]),
])
eq(result['fast'], 'site=ber/ber', 'equal tag')
eq(result['loop'], 'role=web/web', 'tag found in the loop')

# The first condition counts, a later rule starts over, no match means empty
result = run(CustomAttributeRule(), [
    custom('both', [condition('site', 'ber'), condition('role', 'web')]),
    custom('next', [condition('role', 'web'), condition('site', 'ber')]),
    custom('failed', [condition('site', 'ber'), condition('role', 'db')]),
    custom('anyway', [], typ='anyway'),
])
eq(result['both'], 'site=ber/ber', 'first of two conditions')
eq(result['next'], 'role=web/web', 'the next rule')
eq('failed' in result, False, 'a rule that did not hit')
eq(result['anyway'], 'None=None/None', 'a rule without conditions')

outcome = {'old_attribute_name': 'role', 'overwrite_name': 'jinja',
           'new_attribute_name': '{{ FIRST_MATCHING_TAG }}_new',
           'overwrite_value': 'jinja', 'new_value': '{{ FIRST_MATCHING_VALUE }}!',
           'action': 'add'}
result = run(Rewrite(), [rule('rewrite', [condition('site', 'ber')], outcome)])
eq(result.get('add_site_new'), 'ber!', f'rewrite in {result}')

print('FIRST_MATCHING_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class FirstMatchingTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_first_matching(self):
        """The templates see what the first matching condition matched."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('FIRST_MATCHING_OK', result.stdout)
