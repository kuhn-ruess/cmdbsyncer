"""
Unit tests for the Rule base class optimizations.
"""
# pylint: disable=missing-function-docstring,protected-access
import unittest
from unittest.mock import Mock, patch

from application.modules.rule.rule import Rule, outcome_delta


class _RuleForTests(Rule):
    def add_outcomes(self, rule, rule_outcomes, outcomes):
        outcomes.setdefault('hits', []).append(rule['name'])
        return outcomes


class TestRuleOptimizations(unittest.TestCase):
    """Tests for low-risk Rule matching optimizations."""
    def setUp(self):
        self.rule = _RuleForTests()
        self.rule.name = 'test-rule'
        self.rule.attributes = {'env': 'prod', 'custom_fields': {'role': 'web'}}

    @patch('application.modules.rule.rule.app')
    def test_exact_attribute_match_shortcuts_full_scan(self, mock_app):
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        condition = {
            'tag': 'env',
            'tag_match': 'equal',
            'tag_match_negate': False,
            'value': 'prod',
            'value_match': 'equal',
            'value_match_negate': False,
        }

        with patch('application.modules.rule.rule.render_jinja', return_value='prod'), \
             patch('application.modules.rule.rule.match', side_effect=[True]) as mock_match:
            self.assertTrue(self.rule._check_attribute_match(condition))

        mock_match.assert_called_once_with('prod', 'prod', 'equal', False)

    @patch('application.modules.rule.rule.app')
    def test_custom_field_match_uses_slow_path_and_rewrites_tag_value(self, mock_app):
        # custom_fields-targeted conditions deliberately skip the fast path
        # (see _check_attribute_match) because the slow loop rewrites tag/value
        # when it finds the matching custom_fields key. The final match() call
        # must therefore see the rewritten (value, needed_value) pair.
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        condition = {
            'tag': 'custom_fields["role"]',
            'tag_match': 'equal',
            'tag_match_negate': False,
            'value': 'web',
            'value_match': 'equal',
            'value_match_negate': False,
        }

        # Iteration order on self.attributes:
        #   1. ('env', 'prod')                       -> tag match fails
        #   2. ('custom_fields', {...}) rewritten to
        #      ('custom_fields["role"]', 'web')      -> tag match, value match
        with patch('application.modules.rule.rule.render_jinja', return_value='web'), \
             patch(
                 'application.modules.rule.rule.match',
                 side_effect=[False, True, True],
             ) as mock_match:
            self.assertTrue(self.rule._check_attribute_match(condition))

        self.assertEqual(mock_match.call_count, 3)
        mock_match.assert_any_call('web', 'web', 'equal', False)

    @patch('application.modules.rule.rule.app')
    def test_check_rules_reuses_serialized_rule_documents(self, mock_app):
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        rule_doc = Mock()
        rule_doc.to_mongo.return_value = {
            'name': 'r1',
            '_id': '1',
            'condition_typ': 'anyway',
            'conditions': [],
            'outcomes': [],
            'last_match': False,
        }
        self.rule.rules = [rule_doc]
        self.rule.debug = False

        first = self.rule.check_rules('host-a')
        second = self.rule.check_rules('host-b')

        self.assertEqual(first, {'hits': ['r1']})
        self.assertEqual(second, {'hits': ['r1']})
        rule_doc.to_mongo.assert_called_once()


class TestDebugOutcomes(unittest.TestCase):
    """The debug run reports each rule's own outcome plus the group total."""
    def setUp(self):
        self.rule = _RuleForTests()
        self.rule.name = 'test-rule'
        self.rule.debug = True

    @staticmethod
    def _rule_doc(name):
        doc = Mock()
        doc.to_mongo.return_value = {
            'name': name,
            '_id': name,
            'condition_typ': 'anyway',
            'conditions': [],
            'outcomes': [],
            'last_match': False,
        }
        return doc

    @patch('application.modules.rule.rule.Console')
    @patch('application.modules.rule.rule.app')
    def test_per_rule_outcome_and_total(self, mock_app, _console):
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        self.rule.rules = [self._rule_doc('r1'), self._rule_doc('r2')]

        total = self.rule.check_rules('host-a')

        self.assertEqual(total, {'hits': ['r1', 'r2']})
        result = self.rule.debug_result()
        self.assertEqual(result['outcomes'], {'hits': ['r1', 'r2']})
        # Each line only shows what that rule added, not the whole sum.
        self.assertEqual(result['rules'][0]['outcome'], {'hits': ['r1']})
        self.assertEqual(result['rules'][1]['outcome'],
                         {'hits': ['r1', 'r2']})

    @patch('application.modules.rule.rule.app')
    def test_no_outcome_key_without_debug(self, mock_app):
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        self.rule.debug = False
        self.rule.rules = [self._rule_doc('r1')]

        self.rule.check_rules('host-a')

        self.assertEqual(self.rule.debug_result(),
                         {'rules': [], 'outcomes': {}})


class TestOutcomeDelta(unittest.TestCase):
    """outcome_delta shows only what a rule really contributed."""

    def test_new_key(self):
        self.assertEqual(outcome_delta({}, {'a': 1}), {'a': 1})

    def test_unchanged_key_is_dropped(self):
        self.assertEqual(outcome_delta({'a': 1}, {'a': 1, 'b': 2}), {'b': 2})

    def test_changed_key_is_kept(self):
        self.assertEqual(outcome_delta({'a': 1}, {'a': 2}), {'a': 2})

    def test_empty_default_placeholder_is_dropped(self):
        # Engines seed their outcome dict with empty defaults — that is
        # not something the rule contributed.
        self.assertEqual(outcome_delta({}, {'folder': '', 'tags': [],
                                            'dont_move': False, 'a': 1}),
                         {'a': 1})

    def test_reset_to_empty_is_kept(self):
        self.assertEqual(outcome_delta({'a': 1}, {'a': ''}), {'a': ''})

    def test_lists(self):
        self.assertEqual(outcome_delta(['a'], ['a', 'b']), ['b'])

    def test_other_types_return_the_result(self):
        self.assertEqual(outcome_delta(None, 'x'), 'x')


class TestGetOutcomesCache(unittest.TestCase):
    """Tests for the per-host outcome cache handling in get_outcomes."""
    def setUp(self):
        self.rule = _RuleForTests()
        self.rule.check_rule_match = Mock(return_value={'hits': ['fresh']})
        self.db_host = Mock()
        self.db_host.hostname = 'host-a'
        self.db_host.cache = {}

    def test_cache_key_defaults_to_class_name(self):
        self.rule.get_outcomes(self.db_host, {})
        self.assertIn('_RuleForTests', self.db_host.cache)
        self.db_host.save.assert_called_once()

    def test_cache_name_scopes_the_cache_slot(self):
        # export_rules sets an account-scoped cache_name because the rule
        # set differs per account (project filters) — two accounts must not
        # share one cache slot.
        self.rule.cache_name = 'CheckmkRulesetRule_account_a'
        self.rule.get_outcomes(self.db_host, {})
        self.assertIn('CheckmkRulesetRule_account_a', self.db_host.cache)

        other = _RuleForTests()
        other.check_rule_match = Mock(return_value={'hits': ['other']})
        other.cache_name = 'CheckmkRulesetRule_account_b'
        result = other.get_outcomes(self.db_host, {})
        self.assertEqual(result, {'hits': ['other']})
        other.check_rule_match.assert_called_once()

    def test_cached_result_is_returned(self):
        self.db_host.cache['_RuleForTests'] = {'hits': ['cached']}
        result = self.rule.get_outcomes(self.db_host, {})
        self.assertEqual(result, {'hits': ['cached']})
        self.rule.check_rule_match.assert_not_called()

    def test_use_cache_false_bypasses_read_and_write(self):
        # Debug evaluations run with a different rule set than the exports
        # and must neither return the export's cached outcomes nor
        # overwrite them.
        self.db_host.cache['_RuleForTests'] = {'hits': ['cached']}
        result = self.rule.get_outcomes(self.db_host, {}, use_cache=False)
        self.assertEqual(result, {'hits': ['fresh']})
        self.assertEqual(self.db_host.cache['_RuleForTests'],
                         {'hits': ['cached']})
        self.db_host.save.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
