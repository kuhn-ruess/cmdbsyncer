"""
Unit tests for checkmk rules module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.rules import (
    CheckmkRulesetRule,
    DefaultRule,
    CheckmkRule,
)


class TestCheckmkRulesetRule(unittest.TestCase):
    """Tests for CheckmkRulesetRule"""

    def setUp(self):
        with patch('application.plugins.checkmk.rules.Rule.__init__',
                    return_value=None):
            self.rule = CheckmkRulesetRule()

    def test_add_outcomes_groups_by_ruleset(self):
        outcomes = {}
        rule_outcomes = [
            {'ruleset': 'active_checks:http', 'value': 'v1'},
            {'ruleset': 'active_checks:http', 'value': 'v2'},
            {'ruleset': 'static_checks:cpu', 'value': 'v3'},
        ]

        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)

        self.assertIn('active_checks:http', result)
        self.assertEqual(len(result['active_checks:http']), 2)
        self.assertIn('static_checks:cpu', result)
        self.assertEqual(len(result['static_checks:cpu']), 1)


class TestDefaultRule(unittest.TestCase):
    """Tests for DefaultRule"""

    def setUp(self):
        with patch('application.plugins.checkmk.rules.Rule.__init__',
                    return_value=None):
            self.rule = DefaultRule()
            self.rule.name = 'default'

    def test_add_outcomes_all_in_default(self):
        outcomes = {}
        rule_outcomes = [{'data': 1}, {'data': 2}]

        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)

        self.assertIn('default', result)
        self.assertEqual(len(result['default']), 2)


class TestCheckmkRule(unittest.TestCase):
    """Tests for CheckmkRule"""

    def setUp(self):
        with patch('application.plugins.checkmk.rules.Rule.__init__',
                    return_value=None):
            self.rule = CheckmkRule()
            self.rule.debug = False
            self.rule.attributes = {}
            self.rule.found_poolfolder_rule = False
            self.rule.db_host = Mock()

    @patch('application.plugins.checkmk.rules.app')
    def test_fix_and_format_foldername_basic(self, mock_app):
        mock_app.config = {'CMK_LOWERCASE_FOLDERNAMES': True}

        with patch.object(self.rule, 'replace',
                          side_effect=lambda x, **kw: x):
            result = self.rule.fix_and_format_foldername('/folder1/folder2')

        self.assertEqual(result, '/folder1/folder2')

    @patch('application.plugins.checkmk.rules.app')
    def test_fix_and_format_foldername_strips_extra_attributes(self, mock_app):
        mock_app.config = {'CMK_LOWERCASE_FOLDERNAMES': True}

        with patch.object(self.rule, 'replace',
                          side_effect=lambda x, **kw: x):
            result = self.rule.fix_and_format_foldername(
                "/folder1|{'title': 'F1'}/folder2")

        self.assertEqual(result, '/folder1/folder2')

    @patch('application.plugins.checkmk.rules.app')
    def test_fix_and_format_foldername_lowercase(self, mock_app):
        mock_app.config = {'CMK_LOWERCASE_FOLDERNAMES': True}

        with patch.object(self.rule, 'replace',
                          side_effect=lambda x, **kw: x):
            result = self.rule.fix_and_format_foldername('/MyFolder')

        self.assertEqual(result, '/myfolder')

    @patch('application.plugins.checkmk.rules.app')
    def test_fix_and_format_strips_trailing_slash(self, mock_app):
        mock_app.config = {'CMK_LOWERCASE_FOLDERNAMES': False}

        with patch.object(self.rule, 'replace',
                          side_effect=lambda x, **kw: x):
            result = self.rule.fix_and_format_foldername('/folder/')

        self.assertEqual(result, '/folder')

    @patch('application.plugins.checkmk.rules.app')
    def test_format_foldername_basic(self, mock_app):
        mock_app.config = {'CMK_LOWERCASE_FOLDERNAMES': False}

        with patch.object(self.rule, 'replace',
                          side_effect=lambda x, **kw: x):
            result = self.rule.format_foldername('/folder1/folder2')

        self.assertEqual(result, '/folder1/folder2')

    @patch('application.plugins.checkmk.rules.app')
    def test_format_foldername_preserves_pipe_attributes(self, mock_app):
        mock_app.config = {'CMK_LOWERCASE_FOLDERNAMES': False}

        with patch.object(self.rule, 'replace',
                          side_effect=lambda x, **kw: x):
            result = self.rule.format_foldername(
                "/folder1|{'title': 'F1'}/folder2")

        self.assertIn("|{'title': 'F1'}", result)

    @patch('application.plugins.checkmk.rules.render_jinja')
    @patch('application.plugins.checkmk.rules.app')
    def test_add_outcomes_move_folder(self, mock_app, mock_render):
        mock_app.config = {'CMK_LOWERCASE_FOLDERNAMES': False}
        mock_render.side_effect = lambda v, **kw: v

        with patch.object(self.rule, 'fix_and_format_foldername',
                          return_value='/target'), \
             patch.object(self.rule, 'format_foldername',
                          return_value='/target'):
            outcomes = {}
            rule_outcomes = [{'action': 'move_folder', 'action_param': '/target'}]
            result = self.rule.add_outcomes(None, rule_outcomes, outcomes)

        self.assertEqual(result['move_folder'], '/target')

    def test_add_outcomes_dont_move(self):
        outcomes = {}
        rule_outcomes = [{'action': 'dont_move', 'action_param': ''}]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)
        self.assertTrue(result['dont_move'])

    def test_add_outcomes_dont_create(self):
        outcomes = {}
        rule_outcomes = [{'action': 'dont_create', 'action_param': ''}]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)
        self.assertTrue(result['dont_create'])

    def test_add_outcomes_dont_update(self):
        outcomes = {}
        rule_outcomes = [{'action': 'dont_update', 'action_param': ''}]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)
        self.assertTrue(result['dont_update'])

    @patch('application.plugins.checkmk.rules.render_jinja')
    def test_add_outcomes_set_parent(self, mock_render):
        mock_render.return_value = 'parent1, parent2'
        self.rule.attributes = {'key': 'val'}
        outcomes = {}
        rule_outcomes = [{'action': 'set_parent', 'action_param': '{{ parents }}'}]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)
        self.assertEqual(result['parents'], ['parent1', 'parent2'])

    def test_add_outcomes_attribute(self):
        outcomes = {}
        rule_outcomes = [
            {'action': 'attribute', 'action_param': 'ipaddress'},
            {'action': 'attribute', 'action_param': 'snmp_community'},
        ]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)
        self.assertEqual(result['attributes'], ['ipaddress', 'snmp_community'])

    def test_add_outcomes_create_cluster(self):
        self.rule.attributes = {'node1': 'host-a', 'node2': 'host-b'}
        outcomes = {}
        rule_outcomes = [
            {'action': 'create_cluster', 'action_param': 'node1, node2'},
        ]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)
        self.assertIn('host-a', result['create_cluster'])
        self.assertIn('host-b', result['create_cluster'])

    def test_add_outcomes_create_cluster_wildcard(self):
        self.rule.attributes = {
            'cluster_node_1': 'host-a',
            'cluster_node_2': 'host-b',
            'other': 'skip',
        }
        outcomes = {}
        rule_outcomes = [
            {'action': 'create_cluster', 'action_param': 'cluster_node_*'},
        ]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)
        self.assertIn('host-a', result['create_cluster'])
        self.assertIn('host-b', result['create_cluster'])

    def test_add_outcomes_prefix_labels(self):
        outcomes = {}
        rule_outcomes = [{'action': 'prefix_labels', 'action_param': 'cmdb/'}]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)
        self.assertEqual(result['label_prefix'], 'cmdb/')

    def test_add_outcomes_only_update_prefixed_labels(self):
        outcomes = {}
        rule_outcomes = [
            {'action': 'only_update_prefixed_labels', 'action_param': 'syncer/'}
        ]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)
        self.assertEqual(result['only_update_prefixed_labels'], 'syncer/')

    def test_add_outcomes_empty_values_removed(self):
        outcomes = {}
        rule_outcomes = [{'action': 'dont_move', 'action_param': ''}]
        result = self.rule.add_outcomes(None, rule_outcomes, outcomes)
        # Empty defaults should be cleaned up
        self.assertNotIn('move_folder', result)
        self.assertNotIn('attributes', result)

    @patch('application.plugins.checkmk.rules.poolfolder')
    def test_check_rule_match_clears_poolfolder(self, mock_poolfolder):
        with patch.object(self.rule, 'check_rules', return_value={}):
            db_host = Mock()
            db_host.hostname = 'test-host'
            db_host.get_folder.return_value = '/old_folder'

            self.rule.check_rule_match(db_host)

            db_host.lock_to_folder.assert_called_once_with(False)
            mock_poolfolder.remove_seat.assert_called_once_with('/old_folder')


if __name__ == '__main__':
    unittest.main(verbosity=2)
