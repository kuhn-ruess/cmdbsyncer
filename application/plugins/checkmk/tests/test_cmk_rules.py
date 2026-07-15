"""
Unit tests for checkmk cmk_rules module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import patch, MagicMock

from types import SimpleNamespace

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
from tests import base_mock_init


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

        sync = _make_sync()
        sync.checkmk_version = '2.3.0'
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


def _make_sync():
    """Build a CheckmkRuleSync with CMK2.__init__ stubbed out."""
    with patch('application.plugins.checkmk.cmk_rules.CMK2.__init__',
               lambda self_param, account=False: base_mock_init(
                   self_param, rulsets_by_type={})):
        return CheckmkRuleSync()


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
        self.sync = _make_sync()
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
        with patch.object(inits, 'CheckmkRuleProject') as proj, \
                patch.object(inits, 'CheckmkRuleSync') as sync:
            proj.objects.return_value.first.return_value = None
            self.assertEqual(
                inits.import_project_rules_from_folder('X', 'acc', '/'), 0)
            sync.assert_not_called()

    def test_counts_only_entries_with_id_and_passes_recursive(self):
        with patch.object(inits, 'CheckmkRuleProject') as proj, \
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
        from application.plugins.checkmk.cmk2 import CmkException  # noqa: E402  pylint: disable=import-outside-toplevel
        with patch.object(inits, 'CheckmkRuleProject') as proj, \
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

    def test_account_filter_selection(self):
        projects = [
            SimpleNamespace(name='all', limit_by_accounts=[]),
            SimpleNamespace(name='only_a', limit_by_accounts=['acc_a']),
            SimpleNamespace(name='a_and_b', limit_by_accounts=['acc_a', 'acc_b']),
            SimpleNamespace(name='only_b', limit_by_accounts=['acc_b']),
        ]
        with patch.object(inits, 'CheckmkRuleProject') as mock_project:
            mock_project.objects.return_value = projects
            for_a = inits.projects_for_account('acc_a')
            for_b = inits.projects_for_account('acc_b')
        # Empty filter applies everywhere; account-specific filters only match.
        self.assertEqual(for_a, ['all', 'only_a', 'a_and_b'])
        self.assertEqual(for_b, ['all', 'a_and_b', 'only_b'])


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
        # Global (no project) rules plus the projects this account is allowed.
        mock_dcd.objects.assert_called_once_with(
            enabled=True, project__in=[None, '', 'proj_a'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
