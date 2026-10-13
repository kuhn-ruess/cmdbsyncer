"""
Unit tests for the Rule base class optimizations.
"""
# pylint: disable=missing-function-docstring,protected-access
import datetime
import importlib.util
import pathlib
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

    @staticmethod
    def _conditional_rule_doc(name, condition_typ, conditions):
        doc = Mock()
        doc.to_mongo.return_value = {
            'name': name,
            '_id': name,
            'condition_typ': condition_typ,
            'conditions': conditions,
            'outcomes': [],
            'last_match': False,
        }
        return doc

    @staticmethod
    def _host_condition(hostname):
        return {'match_type': 'host', 'hostname': hostname,
                'hostname_match': 'equal', 'hostname_match_negate': False}

    @patch('application.modules.rule.rule.Console')
    @patch('application.modules.rule.rule.app')
    def test_all_rule_shows_every_matching_condition(self, mock_app, _console):
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        conditions = [self._host_condition('a'), self._host_condition('b'),
                      self._host_condition('c')]
        self.rule.rules = [self._conditional_rule_doc('r1', 'all', conditions)]

        with patch.object(self.rule, 'handle_match', return_value=True):
            self.rule.check_rules('host-a')

        line = self.rule.debug_result()['rules'][0]
        self.assertTrue(line['hit'])
        self.assertEqual(line['match_reasons'], conditions)

    @patch('application.modules.rule.rule.Console')
    @patch('application.modules.rule.rule.app')
    def test_any_rule_shows_the_condition_that_matched(self, mock_app, _console):
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        conditions = [self._host_condition('a'), self._host_condition('b'),
                      self._host_condition('c')]
        self.rule.rules = [self._conditional_rule_doc('r1', 'any', conditions)]

        with patch.object(self.rule, 'handle_match',
                          side_effect=[False, True]):
            self.rule.check_rules('host-a')

        line = self.rule.debug_result()['rules'][0]
        self.assertTrue(line['hit'])
        self.assertEqual(line['match_reasons'], [conditions[1]])

    @patch('application.modules.rule.rule.Console')
    @patch('application.modules.rule.rule.app')
    def test_all_rule_miss_shows_first_failing_condition(self, mock_app, _console):
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        conditions = [self._host_condition('a'), self._host_condition('b')]
        self.rule.rules = [self._conditional_rule_doc('r1', 'all', conditions)]

        with patch.object(self.rule, 'handle_match',
                          side_effect=[True, False]):
            self.rule.check_rules('host-a')

        line = self.rule.debug_result()['rules'][0]
        self.assertFalse(line['hit'])
        self.assertEqual(line['match_reasons'], [])
        self.assertEqual(line['no_match_reason'], conditions[1])

    @patch('application.modules.rule.rule.app')
    def test_no_outcome_key_without_debug(self, mock_app):
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        self.rule.debug = False
        self.rule.rules = [self._rule_doc('r1')]

        self.rule.check_rules('host-a')

        self.assertEqual(self.rule.debug_result(),
                         {'rules': [], 'outcomes': {}})


def _real_custom_attribute_rule():
    """
    The real CustomAttributeRule engine. tests/__init__.py stubs its module
    for the plugin tests, so it is loaded straight from its file here.
    """
    path = (pathlib.Path(__file__).resolve().parent.parent
            / 'application' / 'modules' / 'custom_attributes' / 'rules.py')
    spec = importlib.util.spec_from_file_location('_real_custom_attr_rules', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CustomAttributeRule


class TestLaterRuleWins(unittest.TestCase):
    """
    Two Custom Attribute rules setting the same attribute: the later rule
    in the sort order wins, and the debug lines say so.
    """
    @staticmethod
    def _rule_doc(name, value):
        doc = Mock()
        doc.to_mongo.return_value = {
            'name': name,
            '_id': name,
            'condition_typ': 'anyway',
            'conditions': [],
            'outcomes': [{'attribute_name': 'role', 'attribute_value': value}],
            'last_match': False,
        }
        return doc

    @patch('application.modules.rule.rule.Console')
    @patch('application.modules.rule.rule.app')
    def test_later_rule_overwrites_and_same_value_is_no_change(self, mock_app,
                                                                _console):
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        engine = _real_custom_attribute_rule()()
        engine.debug = True
        engine.attributes = {}
        engine.rules = [self._rule_doc('r1', 'web'),
                        self._rule_doc('r2', 'db'),
                        self._rule_doc('r3', 'db')]

        total = engine.check_rules('host-a')

        self.assertEqual(total, {'role': 'db'})
        lines = engine.debug_result()['rules']
        self.assertEqual(lines[0]['outcome'], {'role': 'web'})
        self.assertEqual(lines[1]['outcome'], {'role': 'db'})
        # Same value as before: the rule hit, but changed nothing.
        self.assertEqual(lines[2]['outcome'], {})


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



class TestTimeDependentRules(unittest.TestCase):
    """
    A rule working with a timestamp answers differently tomorrow, so its
    rule set never goes through the outcome cache.
    """
    OFFLINE_PARAM = ("{{ 'offline' if syncer_last_seen is defined and "
                     "syncer_last_seen and (datetime.datetime.utcnow() - "
                     "syncer_last_seen).days > 2 else 'prod' }}")

    def setUp(self):
        self.rule = _RuleForTests()
        self.rule.check_rule_match = Mock(return_value={'hits': ['fresh']})
        self.db_host = Mock()
        self.db_host.hostname = 'host-a'
        self.db_host.cache = {}

    @staticmethod
    def _rule_doc(outcomes=None, conditions=None):
        doc = Mock()
        doc.to_mongo.return_value = {
            'name': 'r1',
            '_id': '1',
            'condition_typ': 'all',
            'conditions': conditions or [],
            'outcomes': outcomes or [],
            'last_match': False,
        }
        return doc

    # -- what counts as working with a timestamp --

    def test_an_age_condition_counts(self):
        # The way it is meant to be written since this release.
        self.rule.rules = [self._rule_doc(conditions=[{
            'match_type': 'tag',
            'tag': 'syncer_last_seen',
            'tag_match': 'equal',
            'value': '2d',
            'value_match': 'older_than',
        }])]
        self.assertTrue(self.rule.depends_on_time())

    def test_a_rendered_timestamp_counts(self):
        # The Jinja form that predates the conditions has to keep working.
        self.rule.rules = [self._rule_doc(
            [{'action': 'set_criticality', 'param': self.OFFLINE_PARAM}])]
        self.assertTrue(self.rule.depends_on_time())

    def test_an_ordinary_rule_does_not(self):
        self.rule.rules = [self._rule_doc(
            [{'action': 'set_criticality', 'param': 'prod'}],
            conditions=[{
                'match_type': 'tag',
                'tag': 'environment',
                'tag_match': 'equal',
                'value': 'prod',
                'value_match': 'equal',
            }])]
        self.assertFalse(self.rule.depends_on_time())

    def test_the_answer_comes_with_the_rule_documents(self):
        # One scan per rule set, not per host.
        doc = self._rule_doc(
            [{'action': 'set_criticality', 'param': self.OFFLINE_PARAM}])
        self.rule.rules = [doc]
        self.assertTrue(self.rule.depends_on_time())
        self.assertTrue(self.rule.depends_on_time())
        doc.to_mongo.assert_called_once()

    # -- what that does to the cache --

    def test_the_outcome_is_not_read_from_the_cache(self):
        # This is the customer's case: the host was away, was given
        # 'offline', and is back. Nothing about it changed except the
        # sighting date, so a cached verdict would be served forever.
        self.rule.rules = [self._rule_doc(
            [{'action': 'set_criticality', 'param': self.OFFLINE_PARAM}])]
        self.db_host.cache['_RuleForTests'] = {'hits': ['offline']}

        result = self.rule.get_outcomes(self.db_host, {})

        self.assertEqual(result, {'hits': ['fresh']})

    def test_the_outcome_is_not_written_to_the_cache(self):
        self.rule.rules = [self._rule_doc(
            [{'action': 'set_criticality', 'param': self.OFFLINE_PARAM}])]

        self.rule.get_outcomes(self.db_host, {})

        self.assertEqual(self.db_host.cache, {})

    def test_a_slot_from_before_is_thrown_away(self):
        # Otherwise it would sit there unread until the timestamp leaves
        # the rule set, and then answer with a verdict from months ago.
        self.rule.rules = [self._rule_doc(
            [{'action': 'set_criticality', 'param': self.OFFLINE_PARAM}])]
        self.db_host.cache['_RuleForTests'] = {'hits': ['offline']}

        self.rule.get_outcomes(self.db_host, {})

        self.assertNotIn('_RuleForTests', self.db_host.cache)
        self.db_host.save.assert_called_once()

    def test_a_deferred_run_only_marks_the_host_dirty(self):
        self.rule.rules = [self._rule_doc(
            [{'action': 'set_criticality', 'param': self.OFFLINE_PARAM}])]
        self.db_host.cache['_RuleForTests'] = {'hits': ['offline']}

        self.rule.get_outcomes(self.db_host, {}, persist_cache=False)

        self.assertNotIn('_RuleForTests', self.db_host.cache)
        self.db_host.save.assert_not_called()
        self.assertTrue(getattr(self.db_host, '_cache_dirty', False))

    def test_an_ordinary_rule_set_still_caches(self):
        # The whole point of asking per rule set: an installation whose
        # rules never mention a time keeps its cache and its export speed.
        self.rule.rules = [self._rule_doc(
            [{'action': 'set_criticality', 'param': 'prod'}])]

        self.rule.get_outcomes(self.db_host, {})

        self.assertEqual(self.db_host.cache['_RuleForTests'],
                         {'hits': ['fresh']})

    # -- the condition inside the engine --

    @patch('application.modules.rule.rule.app')
    def test_a_host_not_seen_for_long_enough_matches(self, mock_app):
        mock_app.config = {'ADVANCED_RULE_DEBUG': False}
        condition = {
            'match_type': 'tag',
            'tag': 'syncer_last_seen',
            'tag_match': 'equal',
            'tag_match_negate': False,
            'value': '2d',
            'value_match': 'older_than',
            'value_match_negate': False,
        }
        self.rule.rules = [self._rule_doc(conditions=[condition])]
        self.rule.debug = False

        self.rule.attributes = {
            'syncer_last_seen': datetime.datetime.utcnow()
                                - datetime.timedelta(days=8),
        }
        self.assertEqual(self.rule.check_rules('host-a'), {'hits': ['r1']})

        # And the host is judged again the moment it is back.
        self.rule.attributes = {
            'syncer_last_seen': datetime.datetime.utcnow(),
        }
        self.assertEqual(self.rule.check_rules('host-a'), {})


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
