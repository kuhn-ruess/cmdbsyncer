"""
Unit tests for checkmk dcd module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from jinja2.exceptions import UndefinedError
from application.plugins.checkmk.dcd import CheckmkDCDRuleSync
from tests import base_mock_init


class TestCheckmkDCDRuleSync(unittest.TestCase):
    """Tests for CheckmkDCDRuleSync"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param,
                           console=Mock(), all_rules=[], debug=False)

        self.init_patcher = patch(
            'application.plugins.checkmk.dcd.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.sync = CheckmkDCDRuleSync()

    def tearDown(self):
        self.init_patcher.stop()

    def test_does_rule_exist_true(self):
        with patch.object(self.sync, 'request',
                          return_value=({'id': 'rule1'}, {})):
            self.assertTrue(self.sync.does_rule_exist('rule1'))

    def test_does_rule_exist_false(self):
        with patch.object(self.sync, 'request', return_value=({}, {})):
            self.assertFalse(self.sync.does_rule_exist('rule1'))

    def test_build_timeranges(self):
        rule = {
            'exclude_time_ranges': [
                {'start_hour': 11, 'start_minute': 0,
                 'end_hour': 13, 'end_minute': 30},
                {'start_hour': 22, 'start_minute': 5,
                 'end_hour': 6, 'end_minute': 0},
            ]
        }
        result = self.sync.build_timeranges(rule)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {'start': '11:00', 'end': '13:30'})
        self.assertEqual(result[1], {'start': '22:05', 'end': '6:00'})

    def test_build_timeranges_empty(self):
        rule = {'exclude_time_ranges': []}
        result = self.sync.build_timeranges(rule)
        self.assertEqual(result, [])

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_build_creation_rules(self, mock_render):
        mock_render.side_effect = lambda tpl, *args, **kw: tpl
        rule = {
            'creation_rules': [
                {
                    'folder_path': '/test',
                    'delete_hosts': False,
                    'host_attributes': [
                        {'attribute_name': 'tag_agent', 'attribute_value': 'no-agent'}
                    ],
                    'host_filters': ['lx1'],
                },
            ]
        }
        result = self.sync.build_creation_rules(rule, {})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['folder_path'], '/test')
        self.assertEqual(result[0]['host_attributes'], {'tag_agent': 'no-agent'})
        self.assertEqual(result[0]['host_filters'], ['lx1'])

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_build_creation_rules_no_filters(self, mock_render):
        mock_render.side_effect = lambda tpl, *args, **kw: tpl
        rule = {
            'creation_rules': [
                {
                    'folder_path': '/test',
                    'delete_hosts': True,
                    'host_attributes': [],
                    'host_filters': [],
                },
            ]
        }
        result = self.sync.build_creation_rules(rule, {})
        self.assertNotIn('host_filters', result[0])

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_build_rule_payload(self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl

        rule = {
            'dcd_id': 'dcd1',
            'title': 'Test DCD',
            'comment': 'A comment',
            'disabled': False,
            'site': 'site1',
            'connector_type': 'piggyback',
            'restricted_source_hosts': [],
            'interval': '60',
            'creation_rules': [],
            'activate_changes_interval': '300',
            'discover_on_creation': True,
            'exclude_time_ranges': [],
            'no_deletion_time_after_init': '120',
            'max_cache_age': '3600',
            'validity_period': '60',
            'documentation_url': '',
        }

        result = self.sync.build_rule_payload(rule, {})
        self.assertEqual(result['dcd_id'], 'dcd1')
        self.assertEqual(result['title'], 'Test DCD')
        self.assertNotIn('documentation_url', result)

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_build_rule_payload_with_doc_url(self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl

        rule = {
            'dcd_id': 'dcd1',
            'title': 'Test',
            'comment': '',
            'disabled': False,
            'site': 'site1',
            'connector_type': 'piggyback',
            'restricted_source_hosts': [],
            'interval': '60',
            'creation_rules': [],
            'activate_changes_interval': '300',
            'discover_on_creation': True,
            'exclude_time_ranges': [],
            'no_deletion_time_after_init': '120',
            'max_cache_age': '3600',
            'validity_period': '60',
            'documentation_url': 'https://docs.example.com',
        }

        result = self.sync.build_rule_payload(rule, {})
        self.assertEqual(result['documentation_url'], 'https://docs.example.com')

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_build_rule_payload_undefined_returns_empty(self, mock_render):
        mock_render.side_effect = UndefinedError("var")

        rule = {
            'dcd_id': '{{ undefined }}',
            'title': 'Test',
            'comment': '',
            'disabled': False,
            'site': 'site1',
            'connector_type': 'piggyback',
            'restricted_source_hosts': [],
            'interval': '60',
            'creation_rules': [],
            'activate_changes_interval': '300',
            'discover_on_creation': True,
            'exclude_time_ranges': [],
            'no_deletion_time_after_init': '120',
            'max_cache_age': '3600',
            'validity_period': '60',
            'documentation_url': '',
        }

        result = self.sync.build_rule_payload(rule, {})
        self.assertEqual(result, {})

    def test_create_rule_in_cmk(self):
        with patch.object(self.sync, 'request') as mock_req:
            mock_req.return_value = (None, {})
            self.sync.create_rule_in_cmk({'dcd_id': 'test1'})

        mock_req.assert_called_once()
        self.assertEqual(mock_req.call_args[1]['method'], 'POST')

    def test_calculate_rules_of_host_adds_unique(self):
        with patch.object(self.sync, 'build_rule_payload',
                          return_value={'dcd_id': 'r1'}):
            self.sync.calculate_rules_of_host(
                'host1', {'type1': [{'rule': 'data'}]}, {})

        self.assertEqual(len(self.sync.all_rules), 1)

    def test_calculate_rules_of_host_skips_empty(self):
        with patch.object(self.sync, 'build_rule_payload', return_value={}):
            self.sync.calculate_rules_of_host(
                'host1', {'type1': [{'rule': 'data'}]}, {})

        self.assertEqual(len(self.sync.all_rules), 0)

    def test_calculate_rules_of_host_no_duplicates(self):
        payload = {'dcd_id': 'r1'}
        with patch.object(self.sync, 'build_rule_payload', return_value=payload):
            self.sync.calculate_rules_of_host(
                'host1', {'type1': [{'rule': '1'}, {'rule': '2'}]}, {})

        self.assertEqual(len(self.sync.all_rules), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
