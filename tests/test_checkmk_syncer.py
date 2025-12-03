"""
Unit tests for the SyncCMK2 class
"""
import unittest
from unittest.mock import Mock, patch, MagicMock, call
import ast
import multiprocessing
from collections import namedtuple

from application.plugins.checkmk.syncer import SyncCMK2
from application.plugins.checkmk.cmk2 import CmkException


class TestSyncCMK2(unittest.TestCase):
    """Test cases for SyncCMK2 class"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_app_config = {
            'CMK_GET_HOST_BY_FOLDER': False,
            'CMK_DONT_DELETE_HOSTS': False,
            'CMK_DETAILED_LOG': True,
            'CMK_BULK_DELETE_HOSTS': True,
            'CMK_BULK_DELETE_OPERATIONS': 100,
            'CMK_BULK_CREATE_HOSTS': True,
            'CMK_BULK_CREATE_OPERATIONS': 50,
            'CMK_BULK_UPDATE_HOSTS': True,
            'CMK_BULK_UPDATE_OPERATIONS': 50,
            'CMK_COLLECT_BULK_OPERATIONS': False,
            'PROCESS_TIMEOUT': 30
        }
        
        # Mock the parent class initialization by patching it to do nothing
        def mock_init(self_param):
            # Initialize minimal required attributes from parent class
            self_param.account_id = 'test_account_123'
            self_param.account_name = 'Test Account'
            self_param.config = {'test': 'config'}
            self_param.log_details = []
            self_param.existing_folders = ['/folder1', '/folder2']
            self_param.existing_folders_attributes = {}
            self_param.custom_folder_attributes = {}
            self_param.checkmk_hosts = {}
            self_param.checkmk_version = '2.3.0'
            self_param.actions = Mock()
            self_param.console = Mock()
            return None
        
        with patch('application.plugins.checkmk.syncer.CMK2.__init__', mock_init):
            self.syncer = SyncCMK2()

    def test_chunks(self):
        """Test chunks static method"""
        test_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        chunks = list(SyncCMK2.chunks(test_list, 3))
        
        expected = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]]
        self.assertEqual(chunks, expected)
        
        # Test with empty list
        empty_chunks = list(SyncCMK2.chunks([], 3))
        self.assertEqual(empty_chunks, [])

    def test_get_host_actions(self):
        """Test get_host_actions method"""
        mock_host = Mock()
        mock_attributes = {'attr1': 'value1'}
        mock_actions_result = {'action1': 'result1'}
        
        self.syncer.actions.get_outcomes.return_value = mock_actions_result
        
        result = self.syncer.get_host_actions(mock_host, mock_attributes)
        
        self.assertEqual(result, mock_actions_result)
        self.syncer.actions.get_outcomes.assert_called_once_with(mock_host, mock_attributes)

    def test_handle_extra_folder_options(self):
        """Test handle_extra_folder_options method"""
        full_path = "/folder1|{'attr1': 'value1'}/folder2|{'attr2': 'value2'}"
        
        self.syncer.handle_extra_folder_options(full_path)
        
        expected = {
            '/folder1': {'attr1': 'value1'},
            '/folder1/folder2': {'attr2': 'value2'}
        }
        self.assertEqual(self.syncer.custom_folder_attributes, expected)

    def test_handle_extra_folder_options_invalid_syntax(self):
        """Test handle_extra_folder_options with invalid syntax"""
        full_path = "/folder1|invalid_dict_syntax"
        
        # Should raise ValueError due to ast.literal_eval
        with self.assertRaises(ValueError):
            self.syncer.handle_extra_folder_options(full_path)

    @patch('application.plugins.checkmk.syncer.app')
    def test_fetch_checkmk_hosts_by_folder(self, mock_app):
        """Test fetch_checkmk_hosts with folder mode"""
        mock_app.config = {**self.mock_app_config, 'CMK_GET_HOST_BY_FOLDER': True}
        
        with patch.object(self.syncer, '_fetch_checkmk_host_by_folder') as mock_fetch_folder:
            self.syncer.fetch_checkmk_hosts()
            mock_fetch_folder.assert_called_once()

    @patch('application.plugins.checkmk.syncer.app')
    def test_fetch_checkmk_hosts_all(self, mock_app):
        """Test fetch_checkmk_hosts with all hosts mode"""
        mock_app.config = {**self.mock_app_config, 'CMK_GET_HOST_BY_FOLDER': False}
        
        with patch.object(self.syncer, 'fetch_all_checkmk_hosts') as mock_fetch_all:
            self.syncer.fetch_checkmk_hosts()
            mock_fetch_all.assert_called_once()

    def test_use_host_limit_by_hostnames(self):
        """Test use_host with hostname limits"""
        self.syncer.config = {'limit_by_hostnames': 'host1, host2, host3'}
        
        # Test included hostname
        result = self.syncer.use_host('host1', 'account1')
        self.assertTrue(result)
        self.assertTrue(self.syncer.limit)
        
        # Test excluded hostname
        result = self.syncer.use_host('host4', 'account1')
        self.assertFalse(result)

    def test_use_host_limit_by_accounts(self):
        """Test use_host with account limits"""
        self.syncer.config = {'limit_by_accounts': 'account1, account2'}
        
        # Test included account
        result = self.syncer.use_host('hostname', 'account1')
        self.assertTrue(result)
        
        # Test excluded account
        result = self.syncer.use_host('hostname', 'account3')
        self.assertFalse(result)

    def test_use_host_deprecated_account_filter(self):
        """Test use_host with deprecated account_filter raises ValueError"""
        self.syncer.config = {'account_filter': 'some_filter'}
        
        with self.assertRaises(ValueError) as context:
            self.syncer.use_host('hostname', 'account')
        
        self.assertIn('migrate', str(context.exception))

    def test_handle_clusters(self):
        """Test handle_clusters method"""
        self.syncer.clusters = [('cluster1', '/folder', {}, ['node1', 'node2'], {})]
        self.syncer.cluster_updates = [('cluster2', ['old_node'], ['new_node'])]
        
        with patch.object(self.syncer, 'create_cluster') as mock_create, \
             patch.object(self.syncer, 'update_cluster_nodes') as mock_update:
            
            self.syncer.handle_clusters()
            
            mock_create.assert_called_once_with('cluster1', '/folder', {}, ['node1', 'node2'], {})
            mock_update.assert_called_once_with('cluster2', ['old_node'], ['new_node'])

    @patch('application.plugins.checkmk.syncer.app')
    @patch('application.plugins.checkmk.syncer.CC')
    @patch('builtins.print')
    def test_cleanup_hosts_disabled(self, mock_print, mock_cc, mock_app):
        """Test cleanup_hosts when deletion is disabled"""
        mock_app.config = {**self.mock_app_config, 'CMK_DONT_DELETE_HOSTS': True}
        mock_cc.OKBLUE = '\033[94m'
        mock_cc.ENDC = '\033[0m'
        mock_cc.WARNING = '\033[93m'
        
        self.syncer.cleanup_hosts()
        
        # Check that print was called with the expected messages
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any('Check if we need to cleanup hosts' in call for call in print_calls))
        self.assertTrue(any('Deletion of Hosts is disabled by setting' in call for call in print_calls))

    @patch('application.plugins.checkmk.syncer.app')
    @patch('application.plugins.checkmk.syncer.CC')
    @patch('builtins.print')
    def test_cleanup_hosts_delete_limit_exceeded(self, mock_print, mock_cc, mock_app):
        """Test cleanup_hosts with delete limit exceeded"""
        mock_app.config = {**self.mock_app_config, 'CMK_DONT_DELETE_HOSTS': False}
        mock_cc.OKBLUE = '\033[94m'
        mock_cc.ENDC = '\033[0m'
        mock_cc.WARNING = '\033[93m'
        
        self.syncer.config = {'dont_delete_hosts_if_more_then': '2'}
        self.syncer.synced_hosts = []
        self.syncer.checkmk_hosts = {
            'host1': {'extensions': {'attributes': {'labels': {'cmdb_syncer': 'test_account_123'}}}},
            'host2': {'extensions': {'attributes': {'labels': {'cmdb_syncer': 'test_account_123'}}}},
            'host3': {'extensions': {'attributes': {'labels': {'cmdb_syncer': 'test_account_123'}}}},
        }
        
        self.syncer.cleanup_hosts()
        
        # Should not delete due to limit
        self.assertIn(('error', 'Not deleting 3 hosts, because limit is set to 2'), 
                      self.syncer.log_details)
        
        # Check that print was called with limit exceeded message
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any('Not deleting 3 hosts' in call for call in print_calls))

    def test_handle_host_success(self):
        """Test handle_host with successful processing"""
        mock_host = Mock()
        mock_host.hostname = 'test-host'
        mock_attributes = {'all': {'attr1': 'value1'}, 'filtered': {}}
        mock_actions = {'action1': 'result1'}
        
        host_actions = {}
        disabled_hosts = []
        
        with patch.object(self.syncer, 'get_attributes', return_value=mock_attributes), \
             patch.object(self.syncer, 'get_host_actions', return_value=mock_actions):
            
            result = self.syncer.handle_host(mock_host, host_actions, disabled_hosts)
            
            self.assertTrue(result)
            self.assertEqual(host_actions['test-host'], (mock_actions, mock_attributes))
            self.assertEqual(len(disabled_hosts), 0)

    def test_handle_host_disabled(self):
        """Test handle_host with disabled host"""
        mock_host = Mock()
        mock_host.hostname = 'disabled-host'
        
        host_actions = {}
        disabled_hosts = []
        
        with patch.object(self.syncer, 'get_attributes', return_value=False):
            result = self.syncer.handle_host(mock_host, host_actions, disabled_hosts)
            
            self.assertFalse(result)
            self.assertNotIn('disabled-host', host_actions)
            self.assertIn('disabled-host', disabled_hosts)

    def test_handle_cmk_folder_basic(self):
        """Test handle_cmk_folder basic functionality"""
        next_actions = {
            'move_folder': '/new/folder'
        }
        
        with patch.object(self.syncer, 'create_folder') as mock_create:
            result = self.syncer.handle_cmk_folder(next_actions)
            
            self.assertEqual(result, '/new/folder')
            mock_create.assert_called_once_with('/new/folder')

    def test_handle_cmk_folder_with_create(self):
        """Test handle_cmk_folder with folder creation"""
        next_actions = {
            'create_folder': '/created/folder',
            'move_folder': '/target/folder'
        }
        
        with patch.object(self.syncer, 'create_folder') as mock_create:
            result = self.syncer.handle_cmk_folder(next_actions)
            
            self.assertEqual(result, '/target/folder')
            mock_create.assert_has_calls([
                call('/created/folder'),
                call('/target/folder')
            ])

    def test_handle_attributes(self):
        """Test handle_attributes method"""
        next_actions = {
            'parents': ['parent1', 'parent2'],
            'custom_attributes': {'custom1': 'value1'},
            'attributes': ['attr1', 'attr2'],
            'remove_attributes': ['remove1'],
            'remove_if_attributes': ['conditional_remove']
        }
        
        attributes = {
            'all': {
                'attr1': 'attr_value1',
                'attr2': 'attr_value2',
                'existing_attr': 'existing_value'
            }
        }
        
        additional_attrs, remove_attrs = self.syncer.handle_attributes(next_actions, attributes)
        
        expected_additional = {
            'parents': ['parent1', 'parent2'],
            'custom1': 'value1',
            'attr1': 'attr_value1',
            'attr2': 'attr_value2'
        }
        
        expected_remove = ['remove1', 'conditional_remove']
        
        self.assertEqual(additional_attrs, expected_additional)
        self.assertEqual(remove_attrs, expected_remove)

    @patch('builtins.print')
    def test_create_or_update_host_new_regular_host(self, mock_print):
        """Test create_or_update_host for new regular host"""
        hostname = 'new-host'
        folder = '/folder'
        labels = {'label1': 'value1'}
        cluster_nodes = []
        additional_attributes = {'attr1': 'value1'}
        remove_attributes = []
        
        with patch.object(self.syncer, 'create_host') as mock_create:
            self.syncer.create_or_update_host(
                hostname, folder, labels, cluster_nodes, additional_attributes,
                remove_attributes, False, False, False
            )
            
            mock_create.assert_called_once_with(hostname, folder, labels, additional_attributes)

    @patch('builtins.print')
    def test_create_or_update_host_new_cluster(self, mock_print):
        """Test create_or_update_host for new cluster"""
        hostname = 'new-cluster'
        folder = '/folder'
        labels = {'label1': 'value1'}
        cluster_nodes = ['node1', 'node2']
        additional_attributes = {'attr1': 'value1'}
        remove_attributes = []
        
        self.syncer.create_or_update_host(
            hostname, folder, labels, cluster_nodes, additional_attributes,
            remove_attributes, False, False, False
        )
        
        # Should be added to clusters queue
        expected_cluster = (hostname, folder, labels, cluster_nodes, additional_attributes)
        self.assertIn(expected_cluster, self.syncer.clusters)

    def test_create_or_update_host_update_existing(self):
        """Test create_or_update_host for existing host update"""
        hostname = 'existing-host'
        self.syncer.checkmk_hosts[hostname] = {
            'extensions': {
                'is_cluster': False,
                'folder': '/old/folder',
                'attributes': {'labels': {}}
            }
        }
        
        with patch.object(self.syncer, 'update_host') as mock_update:
            self.syncer.create_or_update_host(
                hostname, '/new/folder', {}, [], {}, [], False, False, False
            )
            
            mock_update.assert_called_once()

    @patch('application.plugins.checkmk.syncer.logger')
    def test_create_folder_single_level(self, mock_logger):
        """Test _create_folder method"""
        parent = '/'
        subfolder = 'testfolder'
        
        with patch.object(self.syncer, 'request') as mock_request:
            mock_request.return_value = (None, {})
            
            self.syncer._create_folder(parent, subfolder)
            
            expected_body = {
                'name': 'testfolder',
                'title': 'testfolder',
                'parent': '/'
            }
            
            mock_request.assert_called_once_with(
                'domain-types/folder_config/collections/all',
                method='POST',
                data=expected_body
            )

    def test_create_folder_with_attributes(self):
        """Test _create_folder with custom attributes"""
        parent = '/'
        subfolder = 'testfolder'
        self.syncer.custom_folder_attributes['/testfolder'] = {
            'title': 'Custom Title',
            'attr1': 'value1'
        }
        
        with patch.object(self.syncer, 'request') as mock_request:
            mock_request.return_value = (None, {})
            
            self.syncer._create_folder(parent, subfolder)
            
            expected_body = {
                'name': 'testfolder',
                'title': 'Custom Title',
                'parent': '/',
                'attributes': {'attr1': 'value1'}
            }
            
            mock_request.assert_called_once_with(
                'domain-types/folder_config/collections/all',
                method='POST',
                data=expected_body
            )

    @patch('application.plugins.checkmk.syncer.app')
    def test_send_bulk_create_host(self, mock_app):
        """Test send_bulk_create_host method"""
        mock_app.config = self.mock_app_config
        
        entries = [
            {'host_name': 'host1', 'folder': '/'},
            {'host_name': 'host2', 'folder': '/'}
        ]
        
        with patch.object(self.syncer, 'request') as mock_request:
            mock_request.return_value = (None, {})
            
            self.syncer.send_bulk_create_host(entries)
            
            mock_request.assert_called_once_with(
                '/domain-types/host_config/actions/bulk-create/invoke',
                method='POST',
                data={'entries': entries}
            )
            self.assertEqual(self.syncer.num_created, 2)

    @patch('application.plugins.checkmk.syncer.app')
    def test_create_host_individual(self, mock_app):
        """Test create_host individual mode"""
        mock_app.config = {**self.mock_app_config, 'CMK_BULK_CREATE_HOSTS': False}
        
        hostname = 'test-host'
        folder = '/folder'
        labels = {'label1': 'value1'}
        
        with patch.object(self.syncer, 'request') as mock_request:
            mock_request.return_value = (None, {})
            
            self.syncer.create_host(hostname, folder, labels)
            
            expected_body = {
                'host_name': 'test-host',
                'folder': '/folder',
                'attributes': {'labels': {'label1': 'value1'}}
            }
            
            mock_request.assert_called_once_with(
                '/domain-types/host_config/collections/all',
                method='POST',
                data=expected_body
            )

    @patch('builtins.print')
    def test_create_cluster_no_nodes(self, mock_print):
        """Test create_cluster with no nodes"""
        self.syncer.create_cluster('cluster1', '/folder', {}, [])
        
        mock_print.assert_called_with('\033[92m *\033[0m Cluster cluster1 not created -> No Nodes')

    @patch('builtins.print')
    def test_create_cluster_with_nodes(self, mock_print):
        """Test create_cluster with nodes"""
        with patch.object(self.syncer, 'request') as mock_request:
            mock_request.return_value = (None, {})
            
            self.syncer.create_cluster('cluster1', '/folder', {'label1': 'value1'}, ['node1', 'node2'])
            
            expected_body = {
                'host_name': 'cluster1',
                'folder': '/folder',
                'attributes': {'labels': {'label1': 'value1'}},
                'nodes': ['node1', 'node2']
            }
            
            mock_request.assert_called_once_with(
                '/domain-types/host_config/collections/clusters',
                method='POST',
                data=expected_body
            )

    def test_get_etag(self):
        """Test get_etag method"""
        result = self.syncer.get_etag('test-host', 'test reason')
        self.assertEqual(result, '*')

    @patch('builtins.print')
    def test_update_cluster_nodes_no_change(self, mock_print):
        """Test update_cluster_nodes with no changes"""
        cmk_nodes = ['node1', 'node2']
        syncer_nodes = ['node2', 'node1']  # Same nodes, different order
        
        # Should not call any updates since sorted lists are the same
        with patch.object(self.syncer, 'request') as mock_request:
            self.syncer.update_cluster_nodes('cluster1', cmk_nodes, syncer_nodes)
            mock_request.assert_not_called()

    @patch('application.plugins.checkmk.syncer.app')
    def test_send_bulk_update_host(self, mock_app):
        """Test send_bulk_update_host method"""
        mock_app.config = self.mock_app_config
        
        entries = [
            {'host_name': 'host1', 'update_attributes': {'attr1': 'value1'}},
            {'host_name': 'host2', 'update_attributes': {'attr2': 'value2'}}
        ]
        
        with patch.object(self.syncer, 'request') as mock_request:
            mock_request.return_value = (None, {})
            
            self.syncer.send_bulk_update_host(entries)
            
            mock_request.assert_called_once_with(
                '/domain-types/host_config/actions/bulk-update/invoke',
                method='PUT',
                data={'entries': entries}
            )
            self.assertEqual(self.syncer.num_updated, 2)

    @patch('application.plugins.checkmk.syncer.logger')
    def test_update_host_no_changes(self, mock_logger):
        """Test update_host when no changes are needed"""
        hostname = 'test-host'
        cmk_host = {
            'extensions': {
                'folder': '/folder',
                'attributes': {'labels': {'label1': 'value1'}}
            }
        }
        
        # Same data, no changes needed
        labels = {'label1': 'value1'}
        additional_attributes = {}
        remove_attributes = []
        
        with patch.object(self.syncer, 'request') as mock_request:
            self.syncer.update_host(hostname, cmk_host, '/folder', labels, 
                                   additional_attributes, remove_attributes, False)
            
            # Should not make any API calls since no changes
            mock_request.assert_not_called()

    @patch('application.plugins.checkmk.syncer.multiprocessing')
    @patch('application.plugins.checkmk.syncer.Host')
    @patch('application.plugins.checkmk.syncer.Progress')
    def test_calculate_attributes_and_rules(self, mock_progress, mock_host, mock_mp):
        """Test calculate_attributes_and_rules method"""
        # Mock database query with proper queryset behavior
        mock_db_objects = Mock()
        mock_db_objects.count.return_value = 2
        mock_db_objects.__iter__ = Mock(return_value=iter([Mock(hostname='host1'), Mock(hostname='host2')]))
        mock_host.objects_by_filter.return_value = mock_db_objects
        
        # Mock multiprocessing components
        mock_manager = Mock()
        mock_dict = {}
        mock_list = []
        mock_manager.dict.return_value = mock_dict
        mock_manager.list.return_value = mock_list
        mock_mp.Manager.return_value = mock_manager
        
        mock_pool = Mock()
        mock_mp.Pool.return_value.__enter__.return_value = mock_pool
        
        # Mock use_host to return True
        with patch.object(self.syncer, 'use_host', return_value=True):
            self.syncer.config = {'settings': {}}
            
            result = self.syncer.calculate_attributes_and_rules()
            
            self.assertEqual(result, mock_dict)

    @patch('application.plugins.checkmk.syncer.Progress')
    @patch('application.plugins.checkmk.syncer.print')
    @patch('application.plugins.checkmk.syncer.log')
    def test_run_method_basic_flow(self, mock_log, mock_print, mock_progress):
        """Test basic flow of run method"""
        # Mock required methods
        with patch.object(self.syncer, 'fetch_checkmk_folders'), \
             patch.object(self.syncer, 'fetch_checkmk_hosts'), \
             patch.object(self.syncer, 'calculate_attributes_and_rules', return_value={}), \
             patch.object(self.syncer, 'handle_clusters'), \
             patch.object(self.syncer, 'cleanup_hosts'), \
             patch.object(self.syncer, 'handle_folders'):
            
            self.syncer.run()
            
            # Verify log details were populated
            log_entries = [entry[0] for entry in self.syncer.log_details]
            self.assertIn('num_total', log_entries)
            self.assertIn('num_created', log_entries)
            self.assertIn('num_updated', log_entries)
            self.assertIn('num_deleted', log_entries)


if __name__ == '__main__':
    unittest.main(verbosity=2)
