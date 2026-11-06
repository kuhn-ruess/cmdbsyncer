"""
The shared fields of the rule models leave the stored documents as they were:
own collection, no _cls, field order as before. The order is also the order of
the forms. See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application.modules.rule.models import FullCondition, AttributeRewriteAction
from application.plugins.checkmk.models import CheckmkFilterRule, CheckmkRewriteAttributeRule
from application.plugins.idoit.models import IdoitRewriteAttributeRule
from application.plugins.jira_cloud.models import JiraCloudFilterRule
from application.plugins.netbox.models import NetboxRewriteAttributeRule
from application.plugins.vmware.models import VMwareRewriteAttributes

REWRITE = ['id', 'name', 'documentation', 'condition_typ', 'conditions',
           'render_full_conditions', 'outcomes', 'render_attribute_rewrite', 'last_match',
           'enabled', 'sort_field']
FILTER = REWRITE[:6] + ['outcomes', 'render_filter_outcome'] + REWRITE[8:]

for model, collection, order in (
        (NetboxRewriteAttributeRule, 'netbox_rewrite_attribute_rule', REWRITE),
        (IdoitRewriteAttributeRule, 'idoit_rewrite_attribute_rule', REWRITE),
        (VMwareRewriteAttributes, 'v_mware_rewrite_attributes', REWRITE),
        (CheckmkRewriteAttributeRule, 'checkmk_rewrite_attribute_rule', REWRITE),
        (CheckmkFilterRule, 'checkmk_filter_rule', FILTER),
        (JiraCloudFilterRule, 'jira_cloud_filter_rule', FILTER)):
    eq(model._get_collection_name(), collection, f'collection of {model.__name__}')
    eq(list(model._fields_ordered), order, f'field order of {model.__name__}')
    eq(model._meta.get('allow_inheritance'), None, f'inheritance of {model.__name__}')
    eq(model._superclasses, ('Document',), f'superclasses of {model.__name__}')

# The fields are one set of objects for the rules of the base class: they still
# hold their own documents.
netbox = NetboxRewriteAttributeRule(
    name='netbox', enabled=True,
    conditions=[FullCondition(match_type='tag')],
    outcomes=[AttributeRewriteAction(overwrite_value='string')]).save()
IdoitRewriteAttributeRule(name='idoit').save()
eq(NetboxRewriteAttributeRule.objects.count(), 1, 'one rule in the netbox collection')
eq(IdoitRewriteAttributeRule.objects.count(), 1, 'one rule in the idoit collection')
stored = NetboxRewriteAttributeRule._get_collection().find_one({'_id': netbox.id})
eq('_cls' in stored, False, 'no _cls stored')
loaded = NetboxRewriteAttributeRule.objects.get(id=netbox.id)
eq(loaded.enabled, True, 'enabled comes back')
eq(len(loaded.conditions), 1, 'conditions come back')
eq(type(loaded.outcomes[0]).__name__, 'AttributeRewriteAction', 'outcomes come back')

eq(JiraCloudFilterRule().enabled, True, 'Jira rules stay enabled by default')
eq(CheckmkFilterRule().enabled, None, 'other rules stay without a default')

print('RULE_FIELDS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class RuleModelFieldsTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_storage_is_unchanged(self):
        """Collections, field order and _cls stay what stored rules expect."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('RULE_FIELDS_OK', result.stdout)
