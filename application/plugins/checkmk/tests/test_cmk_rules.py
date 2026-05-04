"""
Unit tests for checkmk cmk_rules module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import patch

from types import SimpleNamespace

from application.plugins.checkmk.cmk_rules import (
    clean_postproccessed,
    deep_compare,
    analyze_value_differences,
    preview_rule_for_attributes,
    preview_group_rule_for_attributes,
    render_jinja_in_value,
    CheckmkRuleSync,
)
from tests import base_mock_init


class TestCleanPostprocessed(unittest.TestCase):
    """Tests for clean_postproccessed"""

    def test_regular_dict_unchanged(self):
        data = {'key1': 'value1', 'key2': 42}
        result = clean_postproccessed(data)
        self.assertEqual(result, data)

    def test_explicit_password_tuple_cleaned(self):
        data = {
            'password': ('cmk_postprocessed', 'explicit_password', ('id', 'secret')),
        }
        result = clean_postproccessed(data)
        expected = {
            'password': ('cmk_postprocessed', 'explicit_password', (None, None)),
        }
        self.assertEqual(result, expected)

    def test_non_password_tuple_unchanged(self):
        data = {'other': ('something', 'else', 'data')}
        result = clean_postproccessed(data)
        self.assertEqual(result, data)

    def test_empty_dict(self):
        result = clean_postproccessed({})
        self.assertEqual(result, {})


class TestDeepCompare(unittest.TestCase):
    """Tests for deep_compare"""

    def test_equal_dicts(self):
        self.assertTrue(deep_compare({'a': 1}, {'a': 1}))

    def test_unequal_dicts_different_keys(self):
        self.assertFalse(deep_compare({'a': 1}, {'b': 1}))

    def test_stored_superset_is_equivalent(self):
        # Checkmk normalises saved values by adding schema defaults.
        # When our value is a subset of the stored one with all shared
        # keys matching, we must treat the rule as up-to-date to avoid
        # endless UPDATE churn.
        self.assertTrue(deep_compare({'a': 1}, {'a': 1, 'b': 'default'}))

    def test_our_superset_is_drift(self):
        # The reverse asymmetry still counts: if WE set a key Checkmk
        # doesn't have, the rule needs a sync.
        self.assertFalse(deep_compare({'a': 1, 'b': 2}, {'a': 1}))

    def test_unequal_dicts_different_values(self):
        self.assertFalse(deep_compare({'a': 1}, {'a': 2}))

    def test_lists_same_order(self):
        self.assertTrue(deep_compare([1, 2, 3], [1, 2, 3]))

    def test_lists_different_order(self):
        self.assertTrue(deep_compare([3, 1, 2], [1, 2, 3]))

    def test_lists_different_content(self):
        self.assertFalse(deep_compare([1, 2], [1, 3]))

    def test_nested_dict_with_lists(self):
        a = {'hosts': ['host1', 'host2'], 'tags': {'env': 'prod'}}
        b = {'hosts': ['host2', 'host1'], 'tags': {'env': 'prod'}}
        self.assertTrue(deep_compare(a, b))

    def test_scalar_comparison(self):
        self.assertTrue(deep_compare(42, 42))
        self.assertFalse(deep_compare(42, 43))
        self.assertTrue(deep_compare('hello', 'hello'))

    def test_password_postprocessed_cleaned(self):
        a = {'password': ('cmk_postprocessed', 'explicit_password', ('id1', 'pw1'))}
        b = {'password': ('cmk_postprocessed', 'explicit_password', ('id2', 'pw2'))}
        self.assertTrue(deep_compare(a, b))


class TestAnalyzeValueDifferences(unittest.TestCase):
    """Tests for analyze_value_differences"""

    def test_dict_missing_keys(self):
        result = analyze_value_differences({'a': 1, 'b': 2}, {'a': 1})
        self.assertIn('Missing keys', result)
        self.assertIn('b', result)

    def test_dict_extra_keys(self):
        result = analyze_value_differences({'a': 1}, {'a': 1, 'c': 3})
        self.assertIn('Extra keys', result)
        self.assertIn('c', result)

    def test_dict_value_diff(self):
        result = analyze_value_differences({'a': 1}, {'a': 2})
        self.assertIn("Key 'a'", result)

    def test_dict_no_diff(self):
        result = analyze_value_differences({'a': 1}, {'a': 1})
        self.assertIn('No specific differences', result)

    def test_list_length_diff(self):
        result = analyze_value_differences([1, 2], [1])
        self.assertIn('List length differs', result)

    def test_list_item_diff(self):
        result = analyze_value_differences([1, 2], [1, 3])
        self.assertIn('Index 1', result)

    def test_scalar_diff(self):
        result = analyze_value_differences(42, 99)
        self.assertIn('Expected', result)
        self.assertIn('Got', result)


class TestCheckmkRuleSync(unittest.TestCase):
    """Tests for CheckmkRuleSync class"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param, rulsets_by_type={})

        self.init_patcher = patch(
            'application.plugins.checkmk.cmk_rules.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.sync = CheckmkRuleSync()

    def tearDown(self):
        self.init_patcher.stop()

    def test_build_rule_hash_deterministic(self):
        h1 = self.sync.build_rule_hash('tpl', {'host': 'a'})
        h2 = self.sync.build_rule_hash('tpl', {'host': 'a'})
        self.assertEqual(h1, h2)

    def test_build_rule_hash_differs(self):
        h1 = self.sync.build_rule_hash('tpl1', {})
        h2 = self.sync.build_rule_hash('tpl2', {})
        self.assertNotEqual(h1, h2)

    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_build_condition_v23(self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl
        rule_params = {
            'value_template': "{'key': 'val'}",
            'folder': '/',
            'comment': 'test',
        }
        attributes = {'all': {'HOSTNAME': 'host1'}}

        result = self.sync.build_condition_and_update_rule_params(
            rule_params, attributes)

        self.assertIn('condition', result)
        self.assertIn('host_label_groups', result['condition'])
        self.assertNotIn('service_labels', result['condition'])

    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_build_condition_v22(self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl
        self.sync.checkmk_version = '2.2.0'
        rule_params = {
            'value_template': "{'key': 'val'}",
            'folder': '/',
            'comment': 'test',
        }
        attributes = {'all': {'HOSTNAME': 'host1'}}

        result = self.sync.build_condition_and_update_rule_params(
            rule_params, attributes)

        self.assertIn('service_labels', result['condition'])

    def test_optimize_rules_merges_hosts(self):
        rule_hash = hash('tpl' + str({}))
        self.sync.rulsets_by_type = {
            'ruleset1': [
                {
                    'optimize': True,
                    'optimize_rule_hash': rule_hash,
                    'condition': {'host_name': {'match_on': ['host1']}},
                    'value': 'v',
                },
                {
                    'optimize': True,
                    'optimize_rule_hash': rule_hash,
                    'condition': {'host_name': {'match_on': ['host2']}},
                    'value': 'v',
                },
            ]
        }

        self.sync.optimize_rules()

        rules = self.sync.rulsets_by_type['ruleset1']
        self.assertEqual(len(rules), 1)
        self.assertIn('host1', rules[0]['condition']['host_name']['match_on'])
        self.assertIn('host2', rules[0]['condition']['host_name']['match_on'])

    def test_optimize_rules_keeps_non_optimizable(self):
        self.sync.rulsets_by_type = {
            'ruleset1': [
                {'optimize': False, 'value': 'v1'},
                {'optimize': False, 'value': 'v2'},
            ]
        }

        self.sync.optimize_rules()

        self.assertEqual(len(self.sync.rulsets_by_type['ruleset1']), 2)

    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    @patch('application.plugins.checkmk.cmk_rules.get_list')
    def test_calculate_rules_of_host_with_loop(self, mock_get_list, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl
        mock_get_list.return_value = ['item1', 'item2']

        host_actions = {
            'ruleset1': [{
                'loop_over_list': True,
                'list_to_loop': 'my_list',
                'value_template': "{'k': 'v'}",
                'folder': '/',
                'comment': 'test',
            }]
        }
        attributes = {
            'all': {'HOSTNAME': 'host1', 'my_list': 'item1,item2'}
        }

        self.sync.calculate_rules_of_host(host_actions, attributes)

        self.assertIn('ruleset1', self.sync.rulsets_by_type)

    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_rule_params_not_mutated_across_hosts(self, mock_render):
        # Regression: the rule-engine caches prepared outcome dicts and
        # hands the same reference to every host. build_condition_...
        # used to `del rule_params['value_template']`, which broke the
        # second host that hit the same rule.
        mock_render.side_effect = lambda tpl, **kw: tpl
        shared_rule_params = {
            'value_template': "{'k': 'v'}",
            'folder': '/',
            'comment': 'test',
            'condition_host': 'host1',
        }
        attributes = {'all': {'HOSTNAME': 'host1'}}

        self.sync.build_condition_and_update_rule_params(
            shared_rule_params, attributes)

        self.assertIn('value_template', shared_rule_params)
        self.assertIn('condition_host', shared_rule_params)

        # Second call with the same dict must still succeed.
        result = self.sync.build_condition_and_update_rule_params(
            shared_rule_params, attributes)
        self.assertIn('condition', result)


def _outcome(**fields):
    """Build a minimal RuleMngmtOutcome stand-in for preview tests."""
    defaults = {
        'ruleset': 'host_groups',
        'folder': '/{{ env }}',
        'folder_index': 0,
        'comment': '',
        'loop_over_list': False,
        'list_to_loop': '',
        'value_template': "'group_{{ HOSTNAME }}'",
        'condition_label_template': '',
        'condition_host': '',
        'condition_service': '',
        'condition_service_label': '',
    }
    defaults.update(fields)
    return SimpleNamespace(**defaults)


def _fake_render_jinja(value, **kwargs):
    """
    Tiny stand-in for syncer_jinja.render_jinja used in preview tests.
    Replaces ``{{ key }}`` placeholders with the value from kwargs.
    """
    if not value:
        return value
    out = str(value)
    for k, v in kwargs.items():
        out = out.replace('{{ ' + k + ' }}', str(v))
        out = out.replace('{{' + k + '}}', str(v))
    return out


def _fake_get_list(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    return [value]


class TestPreviewRuleForAttributes(unittest.TestCase):
    """Tests for preview_rule_for_attributes (host-debug GUI helper)"""

    def setUp(self):
        # The test harness stubs render_jinja/get_list as MagicMocks.
        # Replace them with tiny real implementations so the preview
        # helper produces deterministic output.
        self.render_patcher = patch(
            'application.plugins.checkmk.cmk_rules.render_jinja',
            side_effect=_fake_render_jinja)
        self.list_patcher = patch(
            'application.plugins.checkmk.cmk_rules.get_list',
            side_effect=_fake_get_list)
        self.render_patcher.start()
        self.list_patcher.start()

    def tearDown(self):
        self.render_patcher.stop()
        self.list_patcher.stop()

    def _row(self, outcome, key):
        return dict(outcome['rows'])[key]

    def test_renders_value_and_folder(self):
        rule = SimpleNamespace(outcomes=[_outcome()])
        attrs = {'HOSTNAME': 'srv01', 'env': 'prod'}
        result = preview_rule_for_attributes(rule, attrs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], 'host_groups')
        self.assertEqual(self._row(result[0], 'value'), "'group_srv01'")
        self.assertEqual(self._row(result[0], 'folder'), '/prod')

    def test_loop_over_list_expands(self):
        rule = SimpleNamespace(outcomes=[_outcome(
            loop_over_list=True, list_to_loop='services',
            value_template="'svc_{{ loop }}'", folder='/',
        )])
        attrs = {'HOSTNAME': 'srv01', 'services': ['web', 'db']}
        result = preview_rule_for_attributes(rule, attrs)
        self.assertEqual([self._row(r, 'value') for r in result],
                         ["'svc_web'", "'svc_db'"])
        self.assertIn('loop[0] = web', result[0]['meta'])
        self.assertIn('loop[1] = db', result[1]['meta'])

    def test_renders_jinja_in_nested_dict(self):
        data = {
            'host_alias': '{{ HOSTNAME }}',
            'tags': ['static', '{{ env }}'],
            'plain': 'no jinja here',
        }
        result = render_jinja_in_value(
            data, {'HOSTNAME': 'srv01', 'env': 'prod'})
        self.assertEqual(result['host_alias'], 'srv01')
        self.assertEqual(result['tags'], ['static', 'prod'])
        self.assertEqual(result['plain'], 'no jinja here')

    def test_loop_over_empty_list_emits_note(self):
        rule = SimpleNamespace(outcomes=[_outcome(
            loop_over_list=True, list_to_loop='missing', folder='/',
        )])
        result = preview_rule_for_attributes(rule, {'HOSTNAME': 'srv01'})
        self.assertEqual(len(result), 1)
        self.assertIn('missing', result[0]['note'])


def _group_outcome(**fields):
    """Build a CmkGroupOutcome stand-in for group-rule preview tests."""
    defaults = {
        'group_name': 'host_groups',
        'foreach_type': 'label',
        'foreach': 'environment',
        'rewrite': '',
        'rewrite_title': '',
    }
    defaults.update(fields)
    return SimpleNamespace(**defaults)


class TestPreviewGroupRule(unittest.TestCase):
    """Tests for preview_group_rule_for_attributes (manage-groups debug)"""

    def setUp(self):
        self.render_patcher = patch(
            'application.plugins.checkmk.cmk_rules.render_jinja',
            side_effect=_fake_render_jinja)
        self.list_patcher = patch(
            'application.plugins.checkmk.cmk_rules.get_list',
            side_effect=_fake_get_list)
        self.render_patcher.start()
        self.list_patcher.start()

    def tearDown(self):
        self.render_patcher.stop()
        self.list_patcher.stop()

    def test_label_foreach_takes_host_value(self):
        rule = SimpleNamespace(
            outcome=_group_outcome(foreach_type='label', foreach='environment'))
        result = preview_group_rule_for_attributes(
            rule, {'HOSTNAME': 'srv01', 'environment': 'prod'})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], 'host_groups: prod')
        rows = dict(result[0]['rows'])
        self.assertEqual(rows['source_item'], 'prod')
        self.assertEqual(rows['group_name'], 'prod')

    def test_label_foreach_missing_emits_note(self):
        rule = SimpleNamespace(
            outcome=_group_outcome(foreach_type='label', foreach='missing'))
        result = preview_group_rule_for_attributes(
            rule, {'HOSTNAME': 'srv01'})
        self.assertEqual(len(result), 1)
        self.assertIn('No matching items', result[0]['note'])

    def test_object_foreach_marked_as_cross_host(self):
        rule = SimpleNamespace(
            outcome=_group_outcome(foreach_type='object', foreach=''))
        result = preview_group_rule_for_attributes(
            rule, {'HOSTNAME': 'srv01'})
        self.assertEqual(len(result), 1)
        self.assertIn('across', result[0]['note'])

    def test_value_foreach_collects_keys(self):
        rule = SimpleNamespace(
            outcome=_group_outcome(foreach_type='value', foreach='prod'))
        result = preview_group_rule_for_attributes(
            rule, {'HOSTNAME': 'srv01', 'environment': 'prod', 'role': 'web'})
        names = sorted(dict(o['rows'])['group_name'] for o in result)
        self.assertEqual(names, ['environment'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
