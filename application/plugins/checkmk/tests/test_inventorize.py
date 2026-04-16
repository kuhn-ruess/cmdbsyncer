"""
Unit tests for checkmk inventorize module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument,no-value-for-parameter
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.inventorize import InventorizeHosts
from application.plugins.checkmk.cmk2 import CmkException
from tests import base_mock_init


class TestInventorizeHosts(unittest.TestCase):
    """Tests for InventorizeHosts"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param,
                           account_name='Test Account', debug=False,
                           fields={}, found_hosts=[],
                           status_inventory={}, hw_sw_inventory={},
                           service_label_inventory={}, config_inventory={},
                           label_inventory={}, checkmk_hosts={})

        self.init_patcher = patch.object(InventorizeHosts, '__init__', mock_init)
        self.init_patcher.start()
        self.inv = InventorizeHosts()

    def tearDown(self):
        self.init_patcher.stop()

    def test_add_host_new(self):
        self.inv.add_host('host1')
        self.assertIn('host1', self.inv.found_hosts)

    def test_add_host_no_duplicate(self):
        self.inv.add_host('host1')
        self.inv.add_host('host1')
        self.assertEqual(len(self.inv.found_hosts), 1)

    def test_run_no_fields_raises(self):
        self.inv.fields = {}
        with self.assertRaises(CmkException):
            self.inv.run()

    @patch('application.plugins.checkmk.inventorize.Host')
    @patch('application.plugins.checkmk.inventorize.app')
    @patch('builtins.print')
    def test_run_writes_to_db(self, mock_print, mock_app, mock_host):
        mock_app.config = {'CMK_GET_HOST_BY_FOLDER': False}
        self.inv.fields = {'cmk_attributes': ['tag_agent']}
        self.inv.found_hosts = ['host1']
        self.inv.config_inventory = {'host1': {'tag_agent': 'cmk-agent'}}

        mock_db_host = Mock()
        mock_host.get_host.return_value = mock_db_host

        with patch.object(self.inv, 'fetch_all_checkmk_hosts'):
            self.inv.checkmk_hosts = {
                'host1': {
                    'extensions': {
                        'effective_attributes': {
                            'tag_agent': 'cmk-agent',
                        },
                        'labels': {},
                    }
                }
            }
            # We only test the DB write part
            self.inv.found_hosts = ['host1']
            self.inv.config_inventory = {'host1': {'tag_agent': 'cmk-agent'}}

            # Call run but mock the fetch methods
            with patch.object(self.inv, 'get_cmk_services'), \
                 patch.object(self.inv, 'get_attr_labels'), \
                 patch.object(self.inv, 'get_hw_sw_inventory'), \
                 patch.object(self.inv, 'get_service_labels'), \
                 patch.object(self.inv, 'fetch_checkmk_folders'):
                self.inv.run()

        mock_host.get_host.assert_called_with('host1', False)
        mock_db_host.save.assert_called_once()

    @patch('application.plugins.checkmk.inventorize.Host')
    @patch('application.plugins.checkmk.inventorize.app')
    @patch('builtins.print')
    def test_run_host_not_in_syncer(self, mock_print, mock_app, mock_host):
        mock_app.config = {'CMK_GET_HOST_BY_FOLDER': False}
        self.inv.fields = {'cmk_attributes': ['tag_agent']}
        self.inv.found_hosts = ['unknown_host']

        mock_host.get_host.return_value = None

        with patch.object(self.inv, 'fetch_all_checkmk_hosts'), \
             patch.object(self.inv, 'get_cmk_services'), \
             patch.object(self.inv, 'get_attr_labels'), \
             patch.object(self.inv, 'get_hw_sw_inventory'), \
             patch.object(self.inv, 'get_service_labels'), \
             patch.object(self.inv, 'fetch_checkmk_folders'):
            self.inv.run()

        # Should not crash, just print error
        mock_host.get_host.assert_called_with('unknown_host', False)

    def test_get_hw_sw_inventory_data_success(self):
        api_response = ({
            'result': {
                'host1': {
                    'Attributes': {
                        'Pairs': {'model': 'PowerEdge'}
                    },
                    'Nodes': {
                        'hardware': {
                            'Attributes': {
                                'Pairs': {'cpu_model': 'Xeon'}
                            }
                        }
                    }
                }
            }
        }, {})

        self.inv.fields = {'cmk_inventory': ['model*', 'hardware*']}
        host_data = {}

        with patch.object(self.inv, 'request', return_value=api_response):
            result = self.inv.get_hw_sw_inventory_data('host1', host_data)

        self.assertTrue(result)
        self.assertIn('host1', host_data)
        self.assertIn('model', host_data['host1'])

    def test_get_hw_sw_inventory_data_empty(self):
        api_response = ({
            'result': {'host1': None}
        }, {})

        self.inv.fields = {'cmk_inventory': ['model']}
        host_data = {}

        with patch.object(self.inv, 'request', return_value=api_response):
            result = self.inv.get_hw_sw_inventory_data('host1', host_data)

        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
