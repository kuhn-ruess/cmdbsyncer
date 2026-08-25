"""
Unit tests for checkmk cmk_rules module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
# pylint: disable=too-many-lines
import unittest
from unittest.mock import patch, MagicMock

from types import SimpleNamespace

from application.plugins.checkmk.cmk2 import CmkException
from application.plugins.checkmk.cmk_rules import (
    clean_postproccessed,
    deep_compare,
    analyze_value_differences,
    preview_rule_for_attributes,
    preview_group_rule_for_attributes,
    render_jinja_in_value,
    normalize_cmk_folder,
    folder_in_scope,
    folder_within_scope,
    cmk_conditions_to_outcome,
    cmk_rule_to_outcome,
    CheckmkRuleSync,
)
import application.plugins.checkmk.inits as inits  # noqa: E402  pylint: disable=consider-using-from-import
from application.plugins.checkmk.helpers import project_allows_account
from tests import base_mock_init, make_checkmk_rule_sync


class _FakeMongo:  # pylint: disable=too-few-public-methods
    """Stand-in for a MongoEngine EmbeddedDocument: exposes to_mongo()."""

    def __init__(self, data):
        self._data = data

    def to_mongo(self):
        return dict(self._data)


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

    def test_strict_rejects_stored_superset(self):
        # enforce_value: a key that is only in Checkmk is drift, not a
        # default — that is how a removed key gets pushed.
        self.assertFalse(
            deep_compare({'a': 1}, {'a': 1, 'b': 'default'}, strict=True))

    def test_strict_rejects_nested_stored_superset(self):
        # The removed key usually sits deep inside the value.
        ours = {'services': {'ec2': {'selection': 'all'}}}
        stored = {'services': {'ec2': {'selection': 'all', 'limits': True}}}
        self.assertTrue(deep_compare(ours, stored))
        self.assertFalse(deep_compare(ours, stored, strict=True))

    def test_strict_accepts_equal_values(self):
        # Once the removal is written, the next run must not update again.
        ours = {'services': {'ec2': {'selection': 'all'}}, 'regions': ['a', 'b']}
        stored = {'services': {'ec2': {'selection': 'all'}}, 'regions': ['b', 'a']}
        self.assertTrue(deep_compare(ours, stored, strict=True))

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

    def test_rule_marker_global(self):
        # Without a project the marker keeps its historical, account-scoped
        # shape so the global export stays backwards compatible.
        self.sync.project = None
        self.assertEqual(self.sync.rule_marker, 'cmdbsyncer_test_account')

    def test_rule_marker_scoped_to_project(self):
        # A project export scopes the marker so its cleanup never touches
        # another project's (or the global) rules on the same instance.
        self.sync.project = 'My Project'
        self.assertEqual(
            self.sync.rule_marker, 'cmdbsyncer_test_account_My_Project')
        # Two different projects must never collide on one account.
        self.sync.project = 'Other'
        self.assertNotEqual(
            self.sync.rule_marker, 'cmdbsyncer_test_account_My_Project')

    def test_rule_marker_slugifies_non_alnum(self):
        self.sync.project = 'proj/one-2'
        self.assertEqual(
            self.sync.rule_marker, 'cmdbsyncer_test_account_proj_one_2')

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
    def test_folder_scope_skips_out_of_scope_rule(self, mock_render):
        # A scoped account (limit_by_folders) drops a rule whose folder is not
        # in scope — build returns None so the caller skips it.
        mock_render.side_effect = lambda tpl, **kw: tpl
        self.sync.config = {'limit_by_folders': '/test'}
        rule_params = {
            'value_template': "{'k': 'v'}", 'folder': '/prod', 'comment': 'c',
        }
        result = self.sync.build_condition_and_update_rule_params(
            rule_params, {'all': {'HOSTNAME': 'h'}})
        self.assertIsNone(result)

    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_folder_scope_keeps_in_scope_rule(self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl
        self.sync.config = {'limit_by_folders': '/test'}
        rule_params = {
            'value_template': "{'k': 'v'}", 'folder': '/test/linux',
            'comment': 'c',
        }
        result = self.sync.build_condition_and_update_rule_params(
            rule_params, {'all': {'HOSTNAME': 'h'}})
        self.assertIsNotNone(result)
        self.assertEqual(result['folder'], '/test/linux')

    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_no_folder_scope_keeps_rule(self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl
        # config without limit_by_folders (the setUp default) — no restriction.
        rule_params = {
            'value_template': "{'k': 'v'}", 'folder': '/prod', 'comment': 'c',
        }
        result = self.sync.build_condition_and_update_rule_params(
            rule_params, {'all': {'HOSTNAME': 'h'}})
        self.assertIsNotNone(result)

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

    @patch('application.plugins.checkmk.cmk_rules.get_list',
           side_effect=lambda v: v if isinstance(v, list) else [v])
    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_anyway_static_condition_host_not_duplicated(
            self, mock_render, mock_get_list):
        # Regression: a CheckmkRuleMngmt with condition_typ "anyway" and a
        # hardcoded condition_host is evaluated for *every* host. The host
        # whose HOSTNAME equals that condition_host takes the optimize path
        # (dict carries optimize/optimize_rule_hash), every other host
        # produces the plain optimize=False variant. Both describe the same
        # Checkmk rule, but the differing bookkeeping keys defeat the
        # `not in` dedup in calculate_rules_of_host, so Checkmk ended up
        # with two identical rules per outcome.
        mock_render.side_effect = lambda tpl, **kw: tpl
        outcome = {
            'value_template': "{'k': 'v'}",
            'folder': '/server/windows',
            'folder_index': 0,
            'comment': '',
            'loop_over_list': False,
            'list_to_loop': '',
            'condition_label_template': '',
            'condition_host': 'fmg-host01',
            'condition_service': '',
            'condition_service_label': '',
        }

        # Owner host: HOSTNAME == condition_host → optimize path.
        self.sync.calculate_rules_of_host(
            {'agent_config:mrpe': [dict(outcome)]},
            {'all': {'HOSTNAME': 'fmg-host01'}})
        # Foreign host: HOSTNAME != condition_host → plain variant.
        self.sync.calculate_rules_of_host(
            {'agent_config:mrpe': [dict(outcome)]},
            {'all': {'HOSTNAME': 'other-host'}})

        self.sync.optimize_rules()

        rules = self.sync.rulsets_by_type['agent_config:mrpe']
        self.assertEqual(len(rules), 1)
        self.assertEqual(
            rules[0]['condition']['host_name']['match_on'], ['fmg-host01'])

    @patch('application.plugins.checkmk.cmk_rules.get_list',
           side_effect=lambda v: v if isinstance(v, list) else [v])
    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_static_rules_calculated_once(self, mock_render, mock_get_list):
        # A static rule is rendered once against an empty context, no
        # matter how many hosts exist — one Checkmk rule per outcome, and
        # never via the per-host optimize path.
        mock_render.side_effect = lambda tpl, **kw: tpl
        # Ruleset map already "fetched": keeps the condition check offline.
        self.sync._ruleset_item_types = {}

        def _outcome_doc(value):
            return _FakeMongo({
                'ruleset': 'agent_config:mrpe',
                'value_template': value,
                'folder': '/server/windows',
                'folder_index': 0,
                'comment': '',
                'loop_over_list': False,
                'list_to_loop': '',
                'condition_label_template': '',
                'condition_host': 'fmg-host01',
                'condition_service': '',
                'condition_service_label': '',
            })

        rule = SimpleNamespace(name='Static', outcomes=[
            _outcome_doc("{'k': 'a'}"), _outcome_doc("{'k': 'b'}")])
        self.sync.static_rules = [rule]

        self.sync.calculate_static_rules()

        rules = self.sync.rulsets_by_type['agent_config:mrpe']
        self.assertEqual(len(rules), 2)
        # Static rules must never take the optimize path.
        self.assertTrue(all(not r['optimize'] for r in rules))

        # optimize_rules + content dedup leave the two distinct outcomes.
        self.sync.optimize_rules()
        self.assertEqual(len(self.sync.rulsets_by_type['agent_config:mrpe']), 2)

    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_static_rule_loop_over_list_skipped(self, mock_render):
        # loop_over_list needs a host attribute list; on a static rule it
        # is skipped (and logged) instead of crashing on missing data.
        mock_render.side_effect = lambda tpl, **kw: tpl
        rule = SimpleNamespace(name='Static', outcomes=[_FakeMongo({
            'ruleset': 'agent_config:mrpe',
            'value_template': "{'k': 'v'}",
            'folder': '/',
            'loop_over_list': True,
            'list_to_loop': 'host_list',
        })])
        self.sync.static_rules = [rule]
        self.sync.log_details = []

        self.sync.calculate_static_rules()

        self.assertEqual(self.sync.rulsets_by_type, {})
        self.assertTrue(any('loop_over_list' in d[1] for d in self.sync.log_details))

    @patch('application.plugins.checkmk.cmk_rules.get_list',
           side_effect=lambda v: v if isinstance(v, list) else [v])
    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_static_rule_bare_loop_flag_still_exported(
            self, mock_render, mock_get_list):
        # loop_over_list without a list attribute name is a meaningless
        # toggle (accidentally ticked in the form) — the outcome must be
        # exported as a plain rule instead of silently vanishing
        # (field report: a project's static rule never reached Checkmk).
        mock_render.side_effect = lambda tpl, **kw: tpl
        # Ruleset map already "fetched": keeps the condition check offline.
        self.sync._ruleset_item_types = {}
        rule = SimpleNamespace(name='Static', outcomes=[_FakeMongo({
            'ruleset': 'special_agents:icinga',
            'value_template': "{'k': 'v'}",
            'folder': '/infrastructure/icwp',
            'folder_index': 0,
            'comment': '',
            'loop_over_list': True,
            'list_to_loop': '',
            'condition_label_template': '',
            'condition_host': 'icwp',
            'condition_service': '',
            'condition_service_label': '',
        })])
        self.sync.static_rules = [rule]
        self.sync.log_details = []

        self.sync.calculate_static_rules()

        rules = self.sync.rulsets_by_type['special_agents:icinga']
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['folder'], '/infrastructure/icwp')
        self.assertEqual(
            rules[0]['condition']['host_name']['match_on'], ['icwp'])
        self.assertEqual(self.sync.log_details, [])

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


class TestUnsupportedConditions(unittest.TestCase):
    """
    Checkmk accepts a rule whose conditions its ruleset does not support
    but stores it without them. Sending one anyway made clean_rules miss
    its own rule, so every export deleted and recreated it.
    """

    def setUp(self):
        self.sync = make_checkmk_rule_sync()

    def test_unsupported_conditions_on_host_ruleset(self):
        # A host ruleset (item_type None) has no service item, so Checkmk
        # stores neither of the two service conditions.
        self.sync._ruleset_item_types = {'active_checks:httpv2': None}
        self.assertEqual(
            self.sync.unsupported_condition_keys('active_checks:httpv2'),
            {'service_description', 'service_labels', 'service_label_groups'})

    def test_unsupported_conditions_on_service_ruleset(self):
        self.sync._ruleset_item_types = {'service_contactgroups': 'service',
                                         'checkgroup_parameters:filesystem': 'item'}
        self.assertEqual(
            self.sync.unsupported_condition_keys('service_contactgroups'), set())
        self.assertEqual(
            self.sync.unsupported_condition_keys(
                'checkgroup_parameters:filesystem'), set())

    def test_unsupported_conditions_on_label_rulesets(self):
        # A ruleset that assigns labels cannot match on the labels it assigns.
        self.sync._ruleset_item_types = {'service_label_rules': 'service',
                                         'host_label_rules': None}
        self.assertEqual(
            self.sync.unsupported_condition_keys('service_label_rules'),
            {'service_labels', 'service_label_groups'})
        # host_label_rules is a host ruleset, so it drops the service
        # conditions on top of its own host labels.
        self.assertEqual(
            self.sync.unsupported_condition_keys('host_label_rules'),
            {'service_description', 'service_labels', 'service_label_groups',
             'host_labels', 'host_label_groups'})

    def test_unsupported_conditions_unknown_ruleset(self):
        # Without knowing the type we must not strip a configured condition.
        self.sync._ruleset_item_types = {'known': 'service'}
        self.assertEqual(self.sync.unsupported_condition_keys('unknown'), set())
        self.assertEqual(self.sync.unsupported_condition_keys(None), set())

    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_build_condition_drops_service_condition_on_host_ruleset(
            self, mock_render):
        # Regression: Checkmk accepts these conditions but stores the rule
        # without them, so clean_rules never found its own rule again and
        # every export deleted and recreated it.
        mock_render.side_effect = lambda tpl, **kw: tpl
        self.sync._ruleset_item_types = {'active_checks:httpv2': None}
        rule_params = {
            'ruleset': 'active_checks:httpv2',
            'value_template': "{'k': 'v'}",
            'folder': '/',
            'comment': 'c',
            'condition_service': 'CPU load',
            'condition_service_label': 'foo:bar',
        }
        result = self.sync.build_condition_and_update_rule_params(
            rule_params, {'all': {'HOSTNAME': 'host1'}})

        condition = result['condition']
        self.assertNotIn('service_description', condition)
        self.assertEqual(condition['service_label_groups'], [])

    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_build_condition_keeps_service_condition_on_service_ruleset(
            self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl
        self.sync._ruleset_item_types = {'service_contactgroups': 'service'}
        rule_params = {
            'ruleset': 'service_contactgroups',
            'value_template': "'all'",
            'folder': '/',
            'comment': 'c',
            'condition_service': 'CPU load',
        }
        result = self.sync.build_condition_and_update_rule_params(
            rule_params, {'all': {'HOSTNAME': 'host1'}})

        # get_list is stubbed in the test bootstrap, so only the presence of
        # the condition is asserted — that it survives is the point here.
        self.assertIn('service_description', result['condition'])
        self.assertEqual(result['condition']['service_description']['operator'],
                         'one_of')

    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_dropped_condition_is_reported_once(self, mock_render):
        # One line per ruleset and key, not one per host.
        mock_render.side_effect = lambda tpl, **kw: tpl
        self.sync._ruleset_item_types = {'active_checks:httpv2': None}
        for hostname in ('host1', 'host2', 'host3'):
            self.sync.build_condition_and_update_rule_params(
                {
                    'ruleset': 'active_checks:httpv2',
                    'value_template': "{'k': 'v'}",
                    'folder': '/',
                    'comment': 'c',
                    'condition_service': 'CPU load',
                },
                {'all': {'HOSTNAME': hostname}})

        warnings = [msg for _level, msg in self.sync.log_details
                    if 'service_description' in msg]
        self.assertEqual(len(warnings), 1)


class _FakeCleanProgress:
    """Stand-in for rich.Progress used by clean_rules (console stubbed)."""
    def __call__(self, *a, **k):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def add_task(self, *a, **k):
        return 1
    def advance(self, *a, **k):
        pass
    def get_default_columns(self, *a, **k):
        return ()


class TestCleanRulesFolderAndKeepValue(unittest.TestCase):
    """clean_rules: wrong-folder correction and keep_value opt-out."""

    def setUp(self):
        self.sync = make_checkmk_rule_sync()
        self.sync.project = None
        self.sync._cmk_order_by_ruleset = {}
        self.sync._rule_etag_wildcard_rejected = None
        self.sync.log_details = []
        self.progress_patcher = patch(
            'application.plugins.checkmk.cmk_rules.Progress',
            _FakeCleanProgress())
        self.progress_patcher.start()

    def tearDown(self):
        self.progress_patcher.stop()

    @staticmethod
    def _cmk_rule(folder, value, comment='c', rule_id='r1'):
        return {
            'id': rule_id,
            'extensions': {
                'folder': folder,
                'value_raw': value,
                'conditions': {'host_name': {'match_on': ['h']}},
                'properties': {
                    'description': 'cmdbsyncer_test_account',
                    'comment': comment,
                },
            },
        }

    def _wire_get(self, cmk_rules):
        calls = {'DELETE': [], 'PUT': []}

        def fake_request(url, method='GET', **_kw):
            if method == 'GET':
                return {'value': cmk_rules}, {}
            if method == 'DELETE':
                calls['DELETE'].append(url)
                return {}, {}
            if method == 'PUT':
                calls['PUT'].append(url)
                return {}, {'status_code': 200}
            return {}, {}
        self.sync.request = MagicMock(side_effect=fake_request)
        return calls

    def test_wrong_folder_is_deleted_and_recreated(self):
        # Same condition/value/comment but the CMK rule lives in the wrong
        # folder: it must be deleted (create_rules then recreates it in the
        # configured folder), not accepted as a match.
        local = {
            'value': "{'k': 'v'}", 'comment': 'c', 'folder': '/correct',
            'condition': {'host_name': {'match_on': ['h']}},
        }
        self.sync.rulsets_by_type = {'ruleset1': [local]}
        calls = self._wire_get([self._cmk_rule('/wrong', "{'k': 'v'}")])

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], ['/objects/rule/r1'])
        # Not paired to the wrong-folder rule -> create_rules recreates it.
        self.assertFalse(local.get('_skip_create'))

    def test_right_folder_full_match_kept(self):
        # Baseline: identical rule in the correct folder is left untouched.
        local = {
            'value': "{'k': 'v'}", 'comment': 'c', 'folder': '/correct',
            'condition': {'host_name': {'match_on': ['h']}},
        }
        self.sync.rulsets_by_type = {'ruleset1': [local]}
        calls = self._wire_get([self._cmk_rule('/correct', "{'k': 'v'}")])

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], [])
        self.assertTrue(local.get('_skip_create'))
        self.assertEqual(local.get('_cmk_id'), 'r1')

    def test_folder_case_insensitive_no_churn(self):
        # Config "/Correct" maps to CMK "/correct" — must not read as drift.
        local = {
            'value': "{'k': 'v'}", 'comment': 'c', 'folder': '/Correct',
            'condition': {'host_name': {'match_on': ['h']}},
        }
        self.sync.rulsets_by_type = {'ruleset1': [local]}
        calls = self._wire_get([self._cmk_rule('/correct', "{'k': 'v'}")])

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], [])
        self.assertTrue(local.get('_skip_create'))

    def test_keep_value_does_not_overwrite_drifted_value(self):
        # keep_value: operator changed the value in CMK. Same condition,
        # comment and folder -> keep the rule, never update or delete it.
        local = {
            'value': "{'k': 'NEW'}", 'comment': 'c', 'folder': '/correct',
            'condition': {'host_name': {'match_on': ['h']}},
            'keep_value': True,
        }
        self.sync.rulsets_by_type = {'ruleset1': [local]}
        calls = self._wire_get([self._cmk_rule('/correct', "{'k': 'OLD'}")])

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], [])
        self.assertEqual(calls['PUT'], [])
        self.assertTrue(local.get('_skip_create'))
        self.assertEqual(local.get('_cmk_id'), 'r1')

    def test_removed_key_is_ignored_without_enforce_value(self):
        # Default tolerance: the key only Checkmk has counts as a schema
        # default, so dropping it from the template changes nothing.
        local = {
            'value': "{'ec2': {'selection': 'all'}}", 'comment': 'c',
            'folder': '/correct',
            'condition': {'host_name': {'match_on': ['h']}},
        }
        self.sync.rulsets_by_type = {'ruleset1': [local]}
        calls = self._wire_get([self._cmk_rule(
            '/correct', "{'ec2': {'selection': 'all', 'limits': True}}")])

        self.sync.clean_rules()

        self.assertEqual(calls['PUT'], [])
        self.assertEqual(calls['DELETE'], [])
        self.assertTrue(local.get('_skip_create'))

    def test_removed_key_is_pushed_with_enforce_value(self):
        # enforce_value: the same removal is drift and gets PUT in place.
        local = {
            'value': "{'ec2': {'selection': 'all'}}", 'comment': 'c',
            'folder': '/correct',
            'condition': {'host_name': {'match_on': ['h']}},
            'enforce_value': True,
        }
        self.sync.rulsets_by_type = {'ruleset1': [local]}
        calls = self._wire_get([self._cmk_rule(
            '/correct', "{'ec2': {'selection': 'all', 'limits': True}}")])

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], [])
        self.assertEqual(len(calls['PUT']), 1)
        self.assertTrue(local.get('_skip_create'))

    def test_value_drift_without_keep_value_updates_in_place(self):
        # Without keep_value a drifted value in the right folder is PUT-updated.
        local = {
            'value': "{'k': 'NEW'}", 'comment': 'c', 'folder': '/correct',
            'condition': {'host_name': {'match_on': ['h']}},
        }
        self.sync.rulsets_by_type = {'ruleset1': [local]}
        calls = self._wire_get([self._cmk_rule('/correct', "{'k': 'OLD'}")])

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], [])
        self.assertEqual(len(calls['PUT']), 1)
        self.assertTrue(local.get('_skip_create'))


class TestHostListDrift(unittest.TestCase):
    """
    ``optimize_rules`` coalesces every host sharing an outcome into one
    rule. A host entering or leaving must adjust that rule in place — the
    old behaviour deleted it and created a new one, which for a rule
    covering hundreds of hosts reads as "the whole export is obsolete".
    """

    def setUp(self):
        self.sync = make_checkmk_rule_sync()
        self.sync.project = None
        self.sync.log_details = []
        self.sync._rule_etag_wildcard_rejected = None
        self.progress_patcher = patch(
            'application.plugins.checkmk.cmk_rules.Progress',
            _FakeCleanProgress())
        self.progress_patcher.start()

    def tearDown(self):
        self.progress_patcher.stop()

    @staticmethod
    def _cmk_rule(hosts, rule_id='r1', value="{'k': 'v'}", comment='c'):
        return {
            'id': rule_id,
            'extensions': {
                'folder': '/',
                'value_raw': value,
                'conditions': {'host_name': {'match_on': list(hosts)}},
                'properties': {
                    'description': 'cmdbsyncer_test_account',
                    'comment': comment,
                },
            },
        }

    @staticmethod
    def _local(hosts, value="{'k': 'v'}", comment='c'):
        return {
            'value': value, 'comment': comment, 'folder': '/',
            'condition': {'host_name': {'match_on': list(hosts)}},
        }

    def _wire(self):
        calls = {'DELETE': [], 'PUT': [], 'GET': []}
        cmk_rules = []

        def fake_request(url, method='GET', data=None, **_kw):
            if method == 'GET' and 'ruleset_name' in url:
                return {'value': cmk_rules}, {}
            if method == 'GET':
                return {}, {'etag': 'x'}
            if method == 'DELETE':
                calls['DELETE'].append(url)
            if method == 'PUT':
                calls['PUT'].append(data)
            return {}, {'status_code': 200}
        self.sync.request = MagicMock(side_effect=fake_request)
        return calls, cmk_rules

    def test_a_dropped_host_updates_the_rule_instead_of_deleting_it(self):
        calls, cmk_rules = self._wire()
        cmk_rules.append(self._cmk_rule(['h1', 'h2', 'h3']))
        local = self._local(['h1', 'h3'])
        self.sync.rulsets_by_type = {'ruleset1': [local]}

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], [])
        self.assertEqual(len(calls['PUT']), 1)
        self.assertEqual(
            calls['PUT'][0]['conditions']['host_name']['match_on'],
            ['h1', 'h3'])
        # Paired: create_rules must not add a second copy.
        self.assertTrue(local.get('_skip_create'))
        self.assertEqual(local.get('_cmk_id'), 'r1')

    def test_an_added_host_updates_the_rule_too(self):
        calls, cmk_rules = self._wire()
        cmk_rules.append(self._cmk_rule(['h1']))
        local = self._local(['h1', 'h2'])
        self.sync.rulsets_by_type = {'ruleset1': [local]}

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], [])
        self.assertEqual(
            calls['PUT'][0]['conditions']['host_name']['match_on'],
            ['h1', 'h2'])

    def test_an_unchanged_rule_is_still_left_alone(self):
        calls, cmk_rules = self._wire()
        cmk_rules.append(self._cmk_rule(['h1', 'h2']))
        local = self._local(['h1', 'h2'])
        self.sync.rulsets_by_type = {'ruleset1': [local]}

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], [])
        self.assertEqual(calls['PUT'], [])
        self.assertTrue(local.get('_skip_create'))

    def test_a_different_value_is_not_treated_as_host_drift(self):
        # Host list AND value differ: we cannot tell this apart from an
        # unrelated rule, so the safe delete + recreate stays.
        calls, cmk_rules = self._wire()
        cmk_rules.append(self._cmk_rule(['h1', 'h2'], value="{'k': 'v'}"))
        local = self._local(['h1'], value="{'k': 'other'}")
        self.sync.rulsets_by_type = {'ruleset1': [local]}

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], ['/objects/rule/r1'])
        self.assertEqual(calls['PUT'], [])
        self.assertFalse(local.get('_skip_create'))

    def test_two_candidates_are_ambiguous_and_left_to_delete(self):
        # Two generated rules differ from the Checkmk one only in the host
        # list — we cannot tell which one it grew out of.
        calls, cmk_rules = self._wire()
        cmk_rules.append(self._cmk_rule(['h1']))
        first = self._local(['h1', 'h2'])
        second = self._local(['h1', 'h3'])
        self.sync.rulsets_by_type = {'ruleset1': [first, second]}

        self.sync.clean_rules()

        self.assertEqual(calls['DELETE'], ['/objects/rule/r1'])
        self.assertEqual(calls['PUT'], [])


class TestExplainDeletion(unittest.TestCase):
    """
    Why a rule is deleted. A run that removes hundreds of its own rules
    is one changed criterion, and the operator has to see which one.
    """

    def setUp(self):
        self.sync = make_checkmk_rule_sync()

    @staticmethod
    def _cmk(condition=None, comment='c', value="{'k': 'v'}", folder='/'):
        return {
            'condition': condition if condition is not None
                         else {'host_name': {'match_on': ['h']}},
            'comment': comment,
            'value': value,
            'folder': folder,
        }

    @staticmethod
    def _local(condition=None, comment='c', value="{'k': 'v'}", folder='/'):
        return {
            'condition': condition if condition is not None
                         else {'host_name': {'match_on': ['h']}},
            'comment': comment,
            'value': value,
            'folder': folder,
        }

    def test_no_rules_left_for_the_ruleset(self):
        reason, _detail = self.sync._explain_deletion([], self._cmk())
        self.assertEqual(reason, 'no rule generated for this ruleset any more')

    def test_condition_no_longer_generated(self):
        # A genuinely different condition, not just another host list.
        local = self._local(condition={'host_labels': [{'key': 'k',
                                                        'operator': 'is',
                                                        'value': 'v'}]})
        reason, detail = self.sync._explain_deletion([local], self._cmk())
        self.assertEqual(reason, 'condition no longer generated')
        self.assertIn('host_labels', detail)

    def test_only_the_host_list_changed(self):
        # optimize_rules coalesces every host sharing an outcome into one
        # condition, so a host entering or leaving is not a different rule.
        local = self._local(
            condition={'host_name': {'match_on': ['h', 'h2']}})
        reason, detail = self.sync._explain_deletion(
            [local], self._cmk(condition={'host_name': {'match_on': ['h']}}))
        self.assertEqual(reason, 'host list changed')
        self.assertIn('h2', detail)

    def test_folder_drift_is_named(self):
        local = self._local(folder='/moved')
        reason, detail = self.sync._explain_deletion([local], self._cmk())
        self.assertEqual(reason, 'folder changed')
        self.assertIn('/moved', detail)

    def test_comment_drift_is_named(self):
        local = self._local(comment='new comment')
        reason, detail = self.sync._explain_deletion([local], self._cmk())
        self.assertEqual(reason, 'comment changed')
        self.assertIn('new comment', detail)

    def test_value_drift_is_named(self):
        local = self._local(value="{'k': 'other'}")
        reason, _detail = self.sync._explain_deletion([local], self._cmk())
        self.assertEqual(reason, 'value changed')

    def test_two_changed_criteria_are_both_named(self):
        local = self._local(comment='new comment', folder='/moved')
        reason, _detail = self.sync._explain_deletion([local], self._cmk())
        self.assertEqual(reason, 'comment and folder changed')

    def test_an_identical_rule_means_a_duplicate_in_checkmk(self):
        # Everything lines up: the generated rule exists, it just paired
        # with another copy of the same rule in Checkmk.
        local = self._local()
        local['_skip_create'] = True
        reason, _detail = self.sync._explain_deletion([local], self._cmk())
        self.assertEqual(reason, 'duplicate in Checkmk')

    def test_the_closest_rule_wins_the_explanation(self):
        # A completely unrelated rule must not shadow the one that only
        # drifted in its folder.
        unrelated = self._local(condition={'host_name': {'match_on': ['x']}},
                                comment='z', value="{'a': 1}", folder='/z')
        close = self._local(folder='/moved')
        reason, _detail = self.sync._explain_deletion(
            [unrelated, close], self._cmk())
        self.assertEqual(reason, 'folder changed')


class TestDeleteReasonSummary(unittest.TestCase):
    """The per-rule lines scroll past; the summary line must not."""

    def setUp(self):
        self.sync = make_checkmk_rule_sync()
        self.sync.log_details = []
        self.sync.debug = False

    def test_reasons_are_counted_and_sorted(self):
        with patch('builtins.print') as printed:
            self.sync._report_delete_reasons(
                {'folder changed': 2, 'condition no longer generated': 900})
        output = " ".join(str(call.args[0]) for call in printed.call_args_list)
        self.assertIn('Removing 902 rule(s)', output)
        self.assertLess(output.index('900x condition'),
                        output.index('2x folder'))
        self.assertTrue(any('Removing 902' in detail
                            for _level, detail in self.sync.log_details))

    def test_nothing_is_printed_without_deletions(self):
        with patch('builtins.print') as printed:
            self.sync._report_delete_reasons({})
        printed.assert_not_called()


class TestExportSurvivesFailedRequests(unittest.TestCase):
    """
    A request that times out (or otherwise errors) must not end the whole
    rules export — every other ruleset is still exported and the next run
    picks the skipped one up again.
    """

    def setUp(self):
        self.sync = make_checkmk_rule_sync()
        self.sync.project = None
        self.sync.log_details = []
        self.sync.config = {}
        self.progress_patcher = patch(
            'application.plugins.checkmk.cmk_rules.Progress',
            _FakeCleanProgress())
        self.progress_patcher.start()

    def tearDown(self):
        self.progress_patcher.stop()

    @staticmethod
    def _cmk_rule(rule_id):
        """A syncer-owned rule in Checkmk that no local rule matches."""
        return {
            'id': rule_id,
            'extensions': {
                'folder': '/',
                'value_raw': "{'stale': 1}",
                'conditions': {'host_name': {'match_on': ['gone']}},
                'properties': {
                    'description': 'cmdbsyncer_test_account',
                    'comment': '',
                },
            },
        }

    def test_a_timeout_skips_only_its_ruleset(self):
        self.sync.rulsets_by_type = {'slow_ruleset': [], 'ok_ruleset': []}
        deletes = []

        def fake_request(url, method='GET', **_kw):
            if method == 'GET' and 'slow_ruleset' in url:
                raise CmkException('Timeout on GET')
            if method == 'GET':
                return {'value': [self._cmk_rule('stale1')]}, {}
            deletes.append(url)
            return {}, {}
        self.sync.request = MagicMock(side_effect=fake_request)

        self.sync.clean_rules()

        # The healthy ruleset was still cleaned up ...
        self.assertEqual(deletes, ['/objects/rule/stale1'])
        # ... and the failed one is remembered for the create step.
        self.assertEqual(self.sync._failed_rulesets, {'slow_ruleset'})

    def test_a_ruleset_we_could_not_read_is_not_created_into(self):
        # Creating without knowing the current state would duplicate every
        # rule that is already there.
        self.sync._failed_rulesets = {'slow_ruleset'}
        self.sync.rulsets_by_type = {
            'slow_ruleset': [{'value': "{'a': 1}", 'comment': '',
                              'folder': '/', 'condition': {}}],
            'ok_ruleset': [{'value': "{'b': 2}", 'comment': '',
                            'folder': '/', 'condition': {}}],
        }
        posted = []

        def fake_request(url, data=None, method='GET', **_kw):
            posted.append(data['ruleset'])
            return [{'id': 'new'}], {}
        self.sync.request = MagicMock(side_effect=fake_request)

        self.sync.create_rules()

        self.assertEqual(posted, ['ok_ruleset'])

    def test_a_failed_delete_does_not_skip_the_next_rule(self):
        self.sync.rulsets_by_type = {'ruleset1': []}
        deletes = []

        def fake_request(url, method='GET', **_kw):
            if method == 'GET':
                return {'value': [self._cmk_rule('stale1'),
                                  self._cmk_rule('stale2')]}, {}
            deletes.append(url)
            if url.endswith('stale1'):
                raise CmkException('Timeout on DELETE')
            return {}, {}
        self.sync.request = MagicMock(side_effect=fake_request)

        self.sync.clean_rules()

        self.assertEqual(deletes,
                         ['/objects/rule/stale1', '/objects/rule/stale2'])

    def test_orphan_cleanup_continues_after_a_failed_ruleset(self):
        self.sync.config = {'remove_orphaned_rules': True}
        self.sync.rulsets_by_type = {}
        deletes = []

        def fake_request(url, method='GET', **_kw):
            if 'ruleset/collections/all?used=true' in url:
                return {'value': [
                    {'id': 'slow', 'extensions': {
                        'name': 'slow', 'number_of_rules': 1}},
                    {'id': 'ok', 'extensions': {
                        'name': 'ok', 'number_of_rules': 1}},
                ]}, {}
            if method == 'GET' and 'ruleset_name=slow' in url:
                raise CmkException('Timeout on GET')
            if method == 'GET':
                return {'value': [
                    {'id': 'mine', 'extensions': {'properties': {
                        'description': 'cmdbsyncer_test_account'}}},
                ]}, {}
            deletes.append(url)
            return {}, {}
        self.sync.request = MagicMock(side_effect=fake_request)

        self.sync.clean_orphaned_rules()

        self.assertEqual(deletes, ['/objects/rule/mine'])


class TestCleanOrphanedRules(unittest.TestCase):
    """clean_orphaned_rules: opt-in removal of no-longer-generated rules."""

    def setUp(self):
        self.sync = make_checkmk_rule_sync()
        self.sync.project = None
        self.sync.log_details = []
        # The run still generates rules for 'active_ruleset' only.
        self.sync.rulsets_by_type = {'active_ruleset': []}

    def _wire(self):
        deletes = []

        def fake_request(url, method='GET', **_kw):
            if 'ruleset/collections/all?used=true' in url:
                # Two used rulesets: one still active, one now orphaned.
                return {'value': [
                    {'id': 'active_ruleset', 'extensions': {
                        'name': 'active_ruleset', 'number_of_rules': 1}},
                    {'id': 'orphan_ruleset', 'extensions': {
                        'name': 'orphan_ruleset', 'number_of_rules': 2}},
                ]}, {}
            if method == 'GET':  # rules of the orphan ruleset
                return {'value': [
                    {'id': 'mine', 'extensions': {'properties': {
                        'description': 'cmdbsyncer_test_account'}}},
                    {'id': 'foreign', 'extensions': {'properties': {
                        'description': 'someone_else'}}},
                ]}, {}
            if method == 'DELETE':
                deletes.append(url)
                return {}, {}
            return {}, {}
        self.sync.request = MagicMock(side_effect=fake_request)
        return deletes

    def test_disabled_when_setting_off(self):
        self.sync.config = {}
        deletes = self._wire()
        self.sync.clean_orphaned_rules()
        self.assertEqual(deletes, [])

    def test_deletes_only_owned_rules_in_orphaned_ruleset(self):
        # Setting on: the orphaned ruleset's syncer-owned rule is deleted,
        # the foreign (unmarked) rule is left untouched, and the still-active
        # ruleset is never scanned.
        self.sync.config = {'remove_orphaned_rules': True}
        deletes = self._wire()
        self.sync.clean_orphaned_rules()
        self.assertEqual(deletes, ['/objects/rule/mine'])


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


class TestCmkFolderHelpers(unittest.TestCase):
    """normalize_cmk_folder + folder_in_scope."""

    def test_normalize_root_variants(self):
        self.assertEqual(normalize_cmk_folder('/'), '/')
        self.assertEqual(normalize_cmk_folder('~'), '/')
        self.assertEqual(normalize_cmk_folder(''), '/')
        self.assertEqual(normalize_cmk_folder(None), '/')

    def test_normalize_tilde_and_slash_equivalent(self):
        self.assertEqual(normalize_cmk_folder('~server~windows'),
                         '/server/windows')
        self.assertEqual(normalize_cmk_folder('/server/windows/'),
                         '/server/windows')
        self.assertEqual(normalize_cmk_folder('//server//windows'),
                         '/server/windows')

    def test_scope_exact_match(self):
        self.assertTrue(folder_in_scope('/server', '/server'))
        self.assertTrue(folder_in_scope('~server', '/server'))

    def test_scope_non_recursive_excludes_subfolder(self):
        self.assertFalse(folder_in_scope('/server/windows', '/server'))

    def test_scope_recursive_includes_subfolder(self):
        self.assertTrue(
            folder_in_scope('/server/windows', '/server', recursive=True))

    def test_scope_recursive_root_matches_all(self):
        self.assertTrue(folder_in_scope('/anything/deep', '/', recursive=True))

    def test_scope_sibling_prefix_not_matched(self):
        # /server must not match /server-old just because of a string prefix.
        self.assertFalse(
            folder_in_scope('/server-old', '/server', recursive=True))

    def test_within_scope_no_limit_allows_all(self):
        self.assertTrue(folder_within_scope('/anything', ''))
        self.assertTrue(folder_within_scope('/anything', None))

    def test_within_scope_recursive_and_leading_slash_tolerant(self):
        # scope typed without a leading slash still matches, recursively.
        self.assertTrue(folder_within_scope('/test/linux', 'test'))
        self.assertTrue(folder_within_scope('/test', '/test,/other'))

    def test_within_scope_out_of_scope_folder(self):
        self.assertFalse(folder_within_scope('/prod', '/test'))
        self.assertFalse(folder_within_scope('/', '/test'))


class TestCmkConditionReverse(unittest.TestCase):
    """cmk_conditions_to_outcome + cmk_rule_to_outcome (reverse of export)."""

    def test_empty_conditions(self):
        result = cmk_conditions_to_outcome({})
        self.assertEqual(result, {
            'condition_host': '',
            'condition_label_template': '',
            'condition_service': '',
            'condition_service_label': '',
        })

    def test_host_name_joined(self):
        result = cmk_conditions_to_outcome(
            {'host_name': {'match_on': ['h1', 'h2'], 'operator': 'one_of'}})
        self.assertEqual(result['condition_host'], 'h1,h2')

    def test_host_label_groups_23(self):
        conditions = {'host_label_groups': [{
            'operator': 'and',
            'label_group': [{'operator': 'and', 'label': 'env:prod'}],
        }]}
        result = cmk_conditions_to_outcome(conditions)
        self.assertEqual(result['condition_label_template'], 'env:prod')

    def test_host_labels_22(self):
        conditions = {'host_labels': [
            {'key': 'env', 'operator': 'is', 'value': 'prod'}]}
        result = cmk_conditions_to_outcome(conditions)
        self.assertEqual(result['condition_label_template'], 'env:prod')

    def test_service_conditions(self):
        conditions = {
            'service_description': {'match_on': ['CPU', 'Mem'],
                                    'operator': 'one_of'},
            'service_label_groups': [{
                'operator': 'and',
                'label_group': [
                    {'operator': 'and', 'label': 'crit:yes'},
                    {'operator': 'and', 'label': 'team:db'},
                ],
            }],
        }
        result = cmk_conditions_to_outcome(conditions)
        self.assertEqual(result['condition_service'], 'CPU,Mem')
        self.assertEqual(result['condition_service_label'], 'crit:yes,team:db')

    def test_rule_to_outcome_full(self):
        cmk_rule = {
            'id': 'rule-123',
            'extensions': {
                'ruleset': 'agent_config:mrpe',
                'folder': '~server~windows',
                'folder_index': 2,
                'properties': {'comment': 'hello', 'disabled': False},
                'value_raw': "{'foo': 'bar'}",
                'conditions': {
                    'host_name': {'match_on': ['srv01'], 'operator': 'one_of'},
                },
            },
        }
        outcome = cmk_rule_to_outcome(cmk_rule)
        self.assertEqual(outcome['ruleset'], 'agent_config:mrpe')
        self.assertEqual(outcome['folder'], '/server/windows')
        self.assertEqual(outcome['folder_index'], 2)
        self.assertEqual(outcome['comment'], 'hello')
        self.assertEqual(outcome['value_template'], "{'foo': 'bar'}")
        self.assertEqual(outcome['condition_host'], 'srv01')
        self.assertFalse(outcome['loop_over_list'])

    @patch('application.plugins.checkmk.cmk_rules.get_list')
    @patch('application.plugins.checkmk.cmk_rules.render_jinja')
    def test_import_export_roundtrip_conditions(self, mock_render, mock_get_list):
        # A rule imported from Checkmk, when rendered by the export side as a
        # static rule, must reproduce the exact same Checkmk conditions.
        mock_render.side_effect = lambda tpl, **kw: tpl
        mock_get_list.side_effect = \
            lambda value: value.split(',') if isinstance(value, str) else value
        original_conditions = {
            'host_tags': [],
            'host_name': {'match_on': ['srv01', 'srv02'], 'operator': 'one_of'},
            'host_label_groups': [{
                'operator': 'and',
                'label_group': [{'operator': 'and', 'label': 'env:prod'}],
            }],
            'service_description': {'match_on': ['CPU'], 'operator': 'one_of'},
        }
        cmk_rule = {
            'id': 'r1',
            'extensions': {
                'ruleset': 'checkgroup_parameters:cpu',
                'folder': '/server',
                'value_raw': "{'levels': (80, 90)}",
                'properties': {},
                'conditions': original_conditions,
            },
        }
        outcome = cmk_rule_to_outcome(cmk_rule)

        sync = make_checkmk_rule_sync()
        sync.checkmk_version = '2.3.0'
        # Ruleset map already "fetched": keeps the condition check offline.
        sync._ruleset_item_types = {}
        rebuilt = sync.build_condition_and_update_rule_params(
            dict(outcome), {'all': {'HOSTNAME': None}})

        cond = rebuilt['condition']
        self.assertEqual(cond['host_name']['match_on'], ['srv01', 'srv02'])
        self.assertEqual(
            cond['host_label_groups'][0]['label_group'][0]['label'],
            'env:prod')
        self.assertEqual(cond['service_description']['match_on'], ['CPU'])
        self.assertEqual(rebuilt['value'], "{'levels': (80, 90)}")
        self.assertEqual(rebuilt['folder'], '/server')


class _FakeProgress:
    """Stand-in for rich.Progress (its console is stubbed out in tests)."""
    def __call__(self, *a, **k):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def add_task(self, *a, **k):
        return 1
    def advance(self, *a, **k):
        pass
    def update(self, *a, **k):
        pass
    def get_default_columns(self, *a, **k):
        return ()


class TestFetchRulesInFolder(unittest.TestCase):
    """CheckmkRuleSync.list_used_rulesets + fetch_rules_in_folder."""

    def setUp(self):
        self.sync = make_checkmk_rule_sync()
        self.progress_patcher = patch(
            'application.plugins.checkmk.cmk_rules.Progress', _FakeProgress())
        self.progress_patcher.start()

    def tearDown(self):
        self.progress_patcher.stop()

    def _wire_requests(self, ruleset_payload, rules_by_ruleset):
        def fake_request(url, method='GET', **_kw):
            if url.startswith('domain-types/ruleset/collections/all'):
                return ruleset_payload, {}
            for name, payload in rules_by_ruleset.items():
                if f'ruleset_name={name}' in url:
                    return payload, {}
            return {'value': []}, {}
        self.sync.request = MagicMock(side_effect=fake_request)

    def test_list_used_rulesets_skips_empty(self):
        self.sync.request = MagicMock(return_value=({'value': [
            {'id': 'a', 'extensions': {'name': 'a', 'number_of_rules': 3}},
            {'id': 'b', 'extensions': {'name': 'b', 'number_of_rules': 0}},
            {'id': 'c', 'extensions': {'number_of_rules': 1}},  # name via id
        ]}, {}))
        self.assertEqual(list(self.sync.list_used_rulesets()), ['a', 'c'])

    def test_fetch_filters_by_folder_non_recursive(self):
        self._wire_requests(
            {'value': [{'id': 'rs1',
                        'extensions': {'name': 'rs1', 'number_of_rules': 2}}]},
            {'rs1': {'value': [
                {'id': 'keep', 'extensions': {
                    'ruleset': 'rs1', 'folder': '/server',
                    'value_raw': '{}', 'properties': {}, 'conditions': {}}},
                {'id': 'drop', 'extensions': {
                    'ruleset': 'rs1', 'folder': '/server/win',
                    'value_raw': '{}', 'properties': {}, 'conditions': {}}},
            ]}})
        result = self.sync.fetch_rules_in_folder('/server')
        self.assertEqual([r['cmk_id'] for r in result], ['keep'])
        self.assertEqual(result[0]['ruleset'], 'rs1')

    def test_fetch_recursive_includes_subfolder(self):
        self._wire_requests(
            {'value': [{'id': 'rs1',
                        'extensions': {'name': 'rs1', 'number_of_rules': 2}}]},
            {'rs1': {'value': [
                {'id': 'a', 'extensions': {
                    'ruleset': 'rs1', 'folder': '/server',
                    'value_raw': '{}', 'properties': {}, 'conditions': {}}},
                {'id': 'b', 'extensions': {
                    'ruleset': 'rs1', 'folder': '~server~win',
                    'value_raw': '{}', 'properties': {'disabled': True},
                    'conditions': {}}},
            ]}})
        result = self.sync.fetch_rules_in_folder('/server', recursive=True)
        self.assertEqual({r['cmk_id'] for r in result}, {'a', 'b'})
        disabled = [r for r in result if r['cmk_id'] == 'b'][0]
        self.assertTrue(disabled['disabled'])

    def test_fetch_no_rulesets_returns_empty(self):
        self._wire_requests({'value': []}, {})
        self.assertEqual(self.sync.fetch_rules_in_folder('/'), [])


class TestImportProjectRules(unittest.TestCase):
    """inits.import_project_rules_from_folder orchestration."""

    def test_missing_project_returns_zero(self):
        with patch.object(inits, 'Project') as proj, \
                patch.object(inits, 'CheckmkRuleSync') as sync:
            proj.objects.return_value.first.return_value = None
            self.assertEqual(
                inits.import_project_rules_from_folder('X', 'acc', '/'), 0)
            sync.assert_not_called()

    def test_counts_only_entries_with_id_and_passes_recursive(self):
        with patch.object(inits, 'Project') as proj, \
                patch.object(inits, 'CheckmkRuleSync') as sync, \
                patch.object(inits, 'CheckmkRuleMngmt'), \
                patch.object(inits, 'RuleMngmtOutcome'):
            proj.objects.return_value.first.return_value = SimpleNamespace(name='P')
            instance = sync.return_value
            instance.fetch_rules_in_folder.return_value = [
                {'cmk_id': 'a', 'outcome': {'ruleset': 'r'}},
                {'cmk_id': None, 'outcome': {'ruleset': 'r'}},   # skipped
                {'cmk_id': 'b', 'outcome': {'ruleset': 'r'}},
            ]
            imported = inits.import_project_rules_from_folder(
                'P', 'acc', '/folder', recursive=True)
            self.assertEqual(imported, 2)
            instance.fetch_rules_in_folder.assert_called_once_with(
                '/folder', recursive=True)

    def test_cmk_error_propagates_and_is_recorded(self):
        """A Checkmk error (e.g. wrong credentials -> 401) must NOT be
        swallowed into a "0 imported" result — it has to reach the caller so
        the CLI/web UI can surface it instead of showing an empty import."""
        with patch.object(inits, 'Project') as proj, \
                patch.object(inits, 'CheckmkRuleSync') as sync:
            proj.objects.return_value.first.return_value = SimpleNamespace(name='P')
            instance = sync.return_value
            instance.fetch_rules_in_folder.side_effect = \
                CmkException('Unauthorized Wrong credentials (Bearer header)')
            with self.assertRaises(CmkException):
                inits.import_project_rules_from_folder('P', 'acc', '/folder')
            instance.record_exception.assert_called_once()


class TestProjectsForAccount(unittest.TestCase):
    """inits.projects_for_account account-filter selection."""

    @staticmethod
    def _project(name, limit=None, deny=None):
        return SimpleNamespace(name=name,
                               limit_by_accounts=limit or [],
                               deny_by_accounts=deny or [])

    def test_account_filter_selection(self):
        projects = [
            self._project('all'),
            self._project('only_a', limit=['acc_a']),
            self._project('a_and_b', limit=['acc_a', 'acc_b']),
            self._project('only_b', limit=['acc_b']),
        ]
        with patch.object(inits, 'Project') as mock_project:
            mock_project.objects.return_value = projects
            for_a = inits.projects_for_account('acc_a')
            for_b = inits.projects_for_account('acc_b')
        # Empty filter applies everywhere; account-specific filters only match.
        self.assertEqual(for_a, ['all', 'only_a', 'a_and_b'])
        self.assertEqual(for_b, ['all', 'a_and_b', 'only_b'])

    def test_deny_list_wins_over_allow_list(self):
        projects = [
            self._project('all_but_a', deny=['acc_a']),
            self._project('a_despite_deny_b', limit=['acc_a', 'acc_b'],
                          deny=['acc_b']),
        ]
        with patch.object(inits, 'Project') as mock_project:
            mock_project.objects.return_value = projects
            for_a = inits.projects_for_account('acc_a')
            for_b = inits.projects_for_account('acc_b')
        # acc_a is denied on the first project; acc_b is on the allow list of
        # the second but the deny list wins.
        self.assertEqual(for_a, ['a_despite_deny_b'])
        self.assertEqual(for_b, ['all_but_a'])


class TestProjectAllowsAccount(unittest.TestCase):
    """helpers.project_allows_account allow/deny evaluation."""

    @staticmethod
    def _allows(account, limit=None, deny=None):
        project = SimpleNamespace(limit_by_accounts=limit or [],
                                  deny_by_accounts=deny or [])
        return project_allows_account(project, account)

    def test_no_filters_allows_everyone(self):
        self.assertTrue(self._allows('any'))

    def test_allow_list_restricts(self):
        self.assertTrue(self._allows('acc_a', limit=['acc_a']))
        self.assertFalse(self._allows('acc_b', limit=['acc_a']))

    def test_deny_list_excludes(self):
        self.assertFalse(self._allows('acc_a', deny=['acc_a']))
        self.assertTrue(self._allows('acc_b', deny=['acc_a']))

    def test_deny_wins_over_allow(self):
        self.assertFalse(self._allows('acc_a', limit=['acc_a'], deny=['acc_a']))

    def test_missing_fields_tolerated(self):
        # Older project documents (or stubs) may lack deny_by_accounts.
        project = SimpleNamespace(limit_by_accounts=None)
        self.assertTrue(project_allows_account(project, 'any'))

    @staticmethod
    def _project(**kwargs):
        fields = {'limit_by_accounts': [], 'deny_by_accounts': [],
                  'rule_limit_by_accounts': [], 'rule_deny_by_accounts': []}
        fields.update(kwargs)
        return SimpleNamespace(**fields)

    def test_rule_kind_uses_rule_lists(self):
        # rule_limit_by_accounts steers rules independently of the host list.
        project = self._project(limit_by_accounts=['prod'],
                                rule_limit_by_accounts=['test'])
        self.assertTrue(project_allows_account(project, 'test', kind='rule'))
        self.assertFalse(project_allows_account(project, 'prod', kind='rule'))
        # Hosts still follow the host list.
        self.assertTrue(project_allows_account(project, 'prod', kind='host'))
        self.assertFalse(project_allows_account(project, 'test', kind='host'))

    def test_rule_kind_falls_back_to_host_list(self):
        # Empty rule lists reuse the host allow/deny lists.
        project = self._project(limit_by_accounts=['prod'],
                                deny_by_accounts=['old'])
        self.assertTrue(project_allows_account(project, 'prod', kind='rule'))
        self.assertFalse(project_allows_account(project, 'test', kind='rule'))
        self.assertFalse(project_allows_account(project, 'old', kind='rule'))

    def test_rule_deny_falls_back_independently(self):
        # A rule allow list set, rule deny empty -> deny falls back to host deny.
        project = self._project(deny_by_accounts=['prod'],
                                rule_limit_by_accounts=['prod', 'test'])
        self.assertFalse(project_allows_account(project, 'prod', kind='rule'))
        self.assertTrue(project_allows_account(project, 'test', kind='rule'))


class TestExportDcdRulesProjectFilter(unittest.TestCase):
    """export_dcd_rules restricts DCD rules by their project's account filter."""

    def test_dcd_export_filters_by_project(self):
        # DefaultRule stand-in (must be subclassable)
        class _StubRule:  # pylint: disable=too-few-public-methods
            def __init__(self, account=None):
                self.rules = None

        # CheckmkDCDRuleSync stand-in
        class _StubSync:  # pylint: disable=too-few-public-methods
            def __init__(self, account=False):
                pass

            def export_rules(self):
                pass

        with patch.object(inits, '_load_rules',
                          return_value={'rewrite': [], 'filter': []}), \
                patch.object(inits, 'projects_for_account',
                             return_value=['proj_a']), \
                patch.object(inits, 'DefaultRule', _StubRule), \
                patch.object(inits, 'CheckmkDCDRuleSync', _StubSync), \
                patch.object(inits, 'CheckmkDCDRule') as mock_dcd:
            mock_dcd.objects.return_value = ['rule']
            inits.export_dcd_rules('acc_a')
        # Global (no project) rules plus the projects this account is allowed,
        # split into the per-host (non-static) and static-rule querysets.
        mock_dcd.objects.assert_any_call(
            enabled=True, static_rule__ne=True, project__in=[None, '', 'proj_a'])
        mock_dcd.objects.assert_any_call(
            enabled=True, static_rule=True, project__in=[None, '', 'proj_a'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
