"""
Unit tests for the Rule base class optimizations.
"""
# pylint: disable=missing-function-docstring,protected-access
import unittest
from unittest.mock import Mock, patch

from application.modules.rule.rule import Rule


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
