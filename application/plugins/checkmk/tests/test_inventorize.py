"""
Unit tests for checkmk inventorize module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument,no-value-for-parameter
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.inventorize import InventorizeHosts
from application.plugins.checkmk.cmk2 import CmkException
from application.helpers.mongo_keys import validate_mongo_keys
from tests import base_mock_init


class TestInventorizeHosts(unittest.TestCase):
    """Tests for InventorizeHosts"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param,
                           account_name='Test Account', debug=False,
                           fields={}, found_hosts=set(),
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
        self.inv.found_hosts = {'host1'}
        self.inv.config_inventory = {'host1': {'tag_agent': 'cmk-agent'}}

        mock_db_host = Mock()
        mock_db_host.hostname = 'host1'
        mock_host.objects.return_value = [mock_db_host]

        with patch.object(self.inv, 'fetch_all_checkmk_hosts'), \
             patch.object(self.inv, 'get_cmk_services'), \
             patch.object(self.inv, 'get_attr_labels'), \
             patch.object(self.inv, 'get_hw_sw_inventory'), \
             patch.object(self.inv, 'get_service_labels'), \
             patch.object(self.inv, 'fetch_checkmk_folders'):
            self.inv.run()

        # Single batched query instead of one get_host per hostname.
        mock_host.objects.assert_called_once_with(hostname__in=['host1'])
        mock_db_host.save.assert_called_once()

    @patch('application.plugins.checkmk.inventorize.Host')
    @patch('application.plugins.checkmk.inventorize.app')
    @patch('builtins.print')
    def test_run_host_not_in_syncer(self, mock_print, mock_app, mock_host):
        mock_app.config = {'CMK_GET_HOST_BY_FOLDER': False}
        self.inv.fields = {'cmk_attributes': ['tag_agent']}
        self.inv.found_hosts = {'unknown_host'}

        # Batched query finds no matches.
        mock_host.objects.return_value = []

        with patch.object(self.inv, 'fetch_all_checkmk_hosts'), \
             patch.object(self.inv, 'get_cmk_services'), \
             patch.object(self.inv, 'get_attr_labels'), \
             patch.object(self.inv, 'get_hw_sw_inventory'), \
             patch.object(self.inv, 'get_service_labels'), \
             patch.object(self.inv, 'fetch_checkmk_folders'):
            self.inv.run()

        mock_host.objects.assert_called_once_with(hostname__in=['unknown_host'])

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

        with patch.object(self.inv, 'request', return_value=api_response):
            hostname, data = self.inv.get_hw_sw_inventory_data('host1')

        self.assertEqual(hostname, 'host1')
        self.assertIsNotNone(data)
        self.assertIn('model', data)

    @patch('application.plugins.checkmk.inventorize.app')
    def test_get_attr_labels_flattens_dots_in_label_names(self, mock_app):
        # Checkmk piggyback source labels embed a FQDN in the label NAME.
        # Those dots would break the MongoDB key validation on write, so
        # get_attr_labels has to flatten them.
        mock_app.config = {'CMK_GET_HOST_BY_FOLDER': False}
        self.inv.checkmk_hosts = {
            'host1': {
                'extensions': {
                    'effective_attributes': None,
                    'labels': {
                        'piggyback_source_vc-prd-w-mgmt.services.p.rz.drv': 'yes',
                        'plain_label': 'value',
                    },
                },
            },
        }
        self.inv.fields = {'cmk_labels': ['piggyback_source_*', 'plain_label']}

        with patch.object(self.inv, 'fetch_all_checkmk_hosts'):
            self.inv.get_attr_labels()

        inv = self.inv.config_inventory['host1']
        self.assertIn('label_piggyback_source_vc-prd-w-mgmt_services_p_rz_drv', inv)
        self.assertNotIn(
            'label_piggyback_source_vc-prd-w-mgmt.services.p.rz.drv', inv,
        )
        self.assertIn('label_plain_label', inv)

    @patch('application.plugins.checkmk.inventorize.app')
    def test_get_attr_labels_keys_pass_mongo_validation(self, mock_app):
        # Regression guard: whatever get_attr_labels writes into
        # config_inventory has to round-trip through the same validator
        # that host.update_inventory() runs at save time. If a future
        # change reintroduces a MongoDB-hostile key (dots, `$`, empty),
        # this test fails before the syncer crashes in production.
        mock_app.config = {'CMK_GET_HOST_BY_FOLDER': False}
        self.inv.checkmk_hosts = {
            'host1': {
                'extensions': {
                    'effective_attributes': None,
                    'labels': {
                        'piggyback_source_host.with.dots.example': 'yes',
                        'cmk/site.name.with.dots': 'prd',
                        'normal_label': 'ok',
                    },
                },
            },
        }
        self.inv.fields = {
            'cmk_labels': ['piggyback_source_*', 'cmk/*', 'normal_label'],
        }

        with patch.object(self.inv, 'fetch_all_checkmk_hosts'):
            self.inv.get_attr_labels()

        # Raises ValueError on any dotted / $-prefixed / empty key.
        validate_mongo_keys(self.inv.config_inventory['host1'], 'inventory')

    def test_get_hw_sw_inventory_data_empty(self):
        api_response = ({
            'result': {'host1': None}
        }, {})

        self.inv.fields = {'cmk_inventory': ['model']}

        with patch.object(self.inv, 'request', return_value=api_response):
            hostname, data = self.inv.get_hw_sw_inventory_data('host1')

        self.assertEqual(hostname, 'host1')
        self.assertIsNone(data)


if __name__ == '__main__':
    unittest.main(verbosity=2)
