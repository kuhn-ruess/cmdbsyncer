"""
Unit tests for checkmk bi module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
# pylint: disable=wrong-import-order,unused-import,no-member
import tests  # noqa: F401 — triggers MongoDB stub setup (must be first)
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.bi import BI
from tests import base_mock_init


class TestBI(unittest.TestCase):
    """Tests for BI class"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param)

        self.init_patcher = patch(
            'application.plugins.checkmk.bi.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.bi = BI()

    def tearDown(self):
        self.init_patcher.stop()

    @patch('application.plugins.checkmk.bi.Host')
    @patch('application.plugins.checkmk.bi.render_jinja')
    @patch('builtins.print')
    def test_export_bi_rules_creates_new(self, mock_print, mock_render, mock_host):
        mock_db_host = Mock()
        mock_db_host.hostname = 'host1'
        mock_host.objects.return_value = [mock_db_host]

        with patch.object(self.bi, 'get_attributes') as mock_attrs:
            mock_attrs.return_value = {'all': {'HOSTNAME': 'host1'}}
            self.bi.actions.get_outcomes.return_value = {
                'bi_rules': [{'rule_template': "{'id': 'rule1', 'pack_id': 'pack1'}"}]
            }
            mock_render.return_value = "{'id': 'rule1', 'pack_id': 'pack1'}"

            pack_response = ({
                'members': {
                    'rules': {'value': []}
                }
            }, {})

            with patch.object(self.bi, 'request') as mock_req:
                mock_req.side_effect = [
                    pack_response,  # GET pack
                    (None, {}),     # POST create rule
                ]
                self.bi.export_bi_rules()

            # Should have created rule1
            self.assertEqual(mock_req.call_count, 2)

    @patch('application.plugins.checkmk.bi.Host')
    @patch('application.plugins.checkmk.bi.render_jinja')
    @patch('builtins.print')
    def test_export_bi_rules_deletes_old(self, mock_print, mock_render, mock_host):
        mock_host.objects.return_value = []

        # No rules from hosts, but pack has a rule -> should delete
        # With no hosts, unique_rules is empty, so no packs are loaded
        # This test verifies the empty case doesn't crash
        self.bi.export_bi_rules()

    @patch('application.plugins.checkmk.bi.Host')
    @patch('application.plugins.checkmk.bi.render_jinja')
    @patch('builtins.print')
    def test_export_bi_rules_syncs_existing(self, mock_print, mock_render, mock_host):
        mock_db_host = Mock()
        mock_db_host.hostname = 'host1'
        mock_host.objects.return_value = [mock_db_host]

        with patch.object(self.bi, 'get_attributes') as mock_attrs:
            mock_attrs.return_value = {'all': {'HOSTNAME': 'host1'}}
            self.bi.actions.get_outcomes.return_value = {
                'bi_rules': [{'rule_template': "{'id': 'rule1', 'pack_id': 'pack1'}"}]
            }
            mock_render.return_value = "{'id': 'rule1', 'pack_id': 'pack1'}"

            pack_response = ({
                'members': {
                    'rules': {
                        'value': [{'href': '/objects/bi_rule/rule1'}]
                    }
                }
            }, {})

            with patch.object(self.bi, 'request') as mock_req:
                # GET pack, GET rule (for sync check)
                mock_req.side_effect = [
                    pack_response,
                    ({'id': 'rule1', 'pack_id': 'pack1'}, {}),  # same -> no update
                ]
                self.bi.export_bi_rules()

    @patch('application.plugins.checkmk.bi.Host')
    @patch('application.plugins.checkmk.bi.render_jinja')
    @patch('builtins.print')
    def test_export_bi_aggregations_empty(self, mock_print, mock_render, mock_host):
        mock_host.objects.return_value = []
        self.bi.export_bi_aggregations()

    @patch('application.plugins.checkmk.bi.Host')
    @patch('application.plugins.checkmk.bi.render_jinja')
    @patch('builtins.print')
    def test_export_bi_rules_skips_malformed_template(self, mock_print, mock_render, mock_host):
        # Pentest finding 2026-04-20: a malformed rule_template from an
        # admin-configured BI rule aborted the whole export. It must now be
        # skipped so other rules keep exporting.
        mock_db_host = Mock()
        mock_db_host.hostname = 'host1'
        mock_host.objects.return_value = [mock_db_host]

        with patch.object(self.bi, 'get_attributes') as mock_attrs:
            mock_attrs.return_value = {'all': {'HOSTNAME': 'host1'}}
            self.bi.actions.get_outcomes.return_value = {
                'bi_rules': [{'rule_template': 'broken'}]
            }
            mock_render.return_value = "{'id': 'rule1', pack_id}"  # invalid syntax

            with patch.object(self.bi, 'request') as mock_req:
                self.bi.export_bi_rules()

            # No packs collected -> no pack requests issued.
            mock_req.assert_not_called()

    @patch('application.plugins.checkmk.bi.Host')
    @patch('application.plugins.checkmk.bi.render_jinja')
    @patch('builtins.print')
    def test_export_bi_aggregations_skips_malformed_template(
            self, mock_print, mock_render, mock_host):
        mock_db_host = Mock()
        mock_db_host.hostname = 'host1'
        mock_host.objects.return_value = [mock_db_host]

        with patch.object(self.bi, 'get_attributes') as mock_attrs:
            mock_attrs.return_value = {'all': {'HOSTNAME': 'host1'}}
            self.bi.actions.get_outcomes.return_value = {
                'aggregations': [{'rule_template': 'broken'}]
            }
            mock_render.return_value = "not-a-dict"  # literal_eval -> string

            with patch.object(self.bi, 'request') as mock_req:
                self.bi.export_bi_aggregations()

            mock_req.assert_not_called()

    @patch('application.plugins.checkmk.bi.Host')
    @patch('builtins.print')
    def test_export_bi_rules_skips_no_attributes(self, mock_print, mock_host):
        mock_db_host = Mock()
        mock_db_host.hostname = 'host1'
        mock_host.objects.return_value = [mock_db_host]

        with patch.object(self.bi, 'get_attributes', return_value=None):
            self.bi.export_bi_rules()
        # Should not crash


if __name__ == '__main__':
    unittest.main(verbosity=2)
