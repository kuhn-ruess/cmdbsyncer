"""
Unit tests for checkmk inventorize module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument,no-value-for-parameter
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.inventorize import (
    InventorizeHosts,
    HW_SW_TREE_SOURCE,
)
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

        with patch.object(self.inv, 'request', return_value=api_response), \
             patch.object(self.inv, '_save_inventory_tree') as save_tree:
            hostname, data = self.inv.get_hw_sw_inventory_data('host1')

        self.assertEqual(hostname, 'host1')
        self.assertIsNotNone(data)
        self.assertIn('model', data)
        # Side-doc save runs in-worker so the full tree never crosses
        # multiprocessing IPC; assert it was handed the full flat dict
        # with the original dotted paths.
        save_tree.assert_called_once()
        save_args = save_tree.call_args.args
        self.assertEqual(save_args[0], 'host1')
        self.assertIn('model', save_args[1])
        self.assertIn('hardware.cpu_model', save_args[1])

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

        with patch.object(self.inv, 'request', return_value=api_response), \
             patch.object(self.inv, '_save_inventory_tree') as save_tree:
            hostname, data = self.inv.get_hw_sw_inventory_data('host1')

        self.assertEqual(hostname, 'host1')
        self.assertIsNone(data)
        # No tree to save when Checkmk has no inventory for the host.
        save_tree.assert_not_called()

    @patch('application.plugins.checkmk.inventorize.HostInventoryTree')
    def test_save_inventory_tree_persists_full_paths(self, mock_tree):
        # The side-doc must carry every key from the flat tree, not just
        # the configured subset. Persistence path is upsert-style: an
        # existing doc gets its paths replaced, otherwise a fresh doc is
        # created. Either way, the original dotted paths survive.
        mock_tree.objects.return_value.first.return_value = None

        flat = {
            'hardware.cpu.model': 'Xeon Gold',
            'software.os.name': 'Linux',
            'unrelated.path': 'value',
        }

        InventorizeHosts._save_inventory_tree('host1', flat)

        mock_tree.objects.assert_called_once_with(
            hostname='host1', source=HW_SW_TREE_SOURCE,
        )
        # New-doc branch: the freshly built HostInventoryTree gets saved.
        mock_tree.assert_called_once()
        kwargs = mock_tree.call_args.kwargs
        self.assertEqual(kwargs['hostname'], 'host1')
        self.assertEqual(kwargs['source'], HW_SW_TREE_SOURCE)
        stored_paths = {p.path for p in kwargs['paths']}
        self.assertEqual(stored_paths, set(flat.keys()))

    @patch('application.plugins.checkmk.inventorize.HostInventoryTree')
    def test_save_inventory_tree_shifts_previous_snapshot(self, mock_tree):
        # On a re-import the existing snapshot has to roll into
        # `previous_paths` BEFORE the new state is written, so the CMDB
        # Tree tab can render the "changes since last import" diff. The
        # previous_update timestamp moves alongside.
        existing = Mock()
        prior_path = Mock()
        prior_path.path = 'hardware.cpu.model'
        prior_path.value = 'Xeon Silver'
        existing.paths = [prior_path]
        existing.last_update = 'prior-timestamp'
        mock_tree.objects.return_value.first.return_value = existing

        InventorizeHosts._save_inventory_tree(
            'host1', {'hardware.cpu.model': 'Xeon Gold'},
        )

        # previous_paths now mirrors the prior snapshot; current paths is
        # the new state.
        self.assertEqual(existing.previous_paths, [prior_path])
        self.assertEqual(existing.previous_update, 'prior-timestamp')
        new_paths = {p.path: p.value for p in existing.paths}
        self.assertEqual(new_paths, {'hardware.cpu.model': 'Xeon Gold'})
        existing.save.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
