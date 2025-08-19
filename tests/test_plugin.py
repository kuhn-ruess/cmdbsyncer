"""
Unit tests for the Plugin base class
"""
import unittest
from unittest.mock import Mock, patch, MagicMock, call
import time
import uuid
from datetime import datetime
from collections import namedtuple

import requests
from mongoengine.errors import DoesNotExist

from application.modules.plugin import Plugin, ResponseDataException


class TestPlugin(unittest.TestCase):
    """Test cases for Plugin class"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_app_config = {
            'HTTP_REQUEST_TIMEOUT': 30,
            'HTTP_MAX_RETRIES': 3,
            'HTTP_REPEAT_TIMEOUT': 5,
            'DISABLE_SSL_ERRORS': False
        }
        
    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.get_account')
    @patch('application.modules.plugin.atexit')
    def test_init_without_account(self, mock_atexit, mock_get_account, mock_app):
        """Test plugin initialization without account"""
        mock_app.config = self.mock_app_config
        
        plugin = Plugin()
        
        self.assertIsNotNone(plugin.start_time)
        self.assertEqual(plugin.name, "Undefined")
        self.assertTrue(plugin.verify)
        self.assertFalse(plugin.dry_run)
        self.assertFalse(plugin.save_requests)
        mock_atexit.register.assert_called_once_with(plugin.save_log)
        mock_get_account.assert_not_called()

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.get_account')
    @patch('application.modules.plugin.atexit')
    def test_init_with_valid_account(self, mock_atexit, mock_get_account, mock_app):
        """Test plugin initialization with valid account"""
        mock_app.config = self.mock_app_config
        mock_account = {
            'name': 'test_account',
            '_id': 'account_id_123',
            'verify_cert': False
        }
        mock_get_account.return_value = mock_account
        
        plugin = Plugin(account='test_account')
        
        self.assertEqual(plugin.account_name, 'test_account')
        self.assertEqual(plugin.account_id, 'account_id_123')
        self.assertFalse(plugin.verify)
        mock_get_account.assert_called_once_with('test_account')

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.get_account')
    def test_init_with_invalid_account(self, mock_get_account, mock_app):
        """Test plugin initialization with invalid account"""
        mock_app.config = self.mock_app_config
        mock_get_account.return_value = None
        
        with self.assertRaises(ValueError) as context:
            Plugin(account='invalid_account')
        
        self.assertEqual(str(context.exception), "Account Invalid or not found")

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.log')
    def test_save_log(self, mock_log, mock_app):
        """Test save_log method"""
        mock_app.config = self.mock_app_config
        
        plugin = Plugin()
        plugin.name = "TestPlugin"
        plugin.source = "TestSource"
        start_time = plugin.start_time
        
        # Simulate some time passing
        time.sleep(0.1)
        
        plugin.save_log()
        
        # Verify log details were added
        self.assertTrue(any(detail[0] == 'duration' for detail in plugin.log_details))
        self.assertTrue(any(detail[0] == 'ended' for detail in plugin.log_details))
        
        # Verify log.log was called
        mock_log.log.assert_called_once()
        call_args = mock_log.log.call_args
        self.assertEqual(call_args[0][0], "TestPlugin")
        self.assertEqual(call_args[1]['source'], "TestSource")

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.requests')
    @patch('application.modules.plugin.logger')
    def test_inner_request_get_success(self, mock_logger, mock_requests, mock_app):
        """Test successful GET request"""
        mock_app.config = self.mock_app_config
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'success'}
        mock_requests.get.return_value = mock_response
        
        plugin = Plugin()
        result = plugin.inner_request('GET', 'http://example.com')
        
        self.assertEqual(result, mock_response)
        mock_requests.get.assert_called_once()

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.requests')
    @patch('application.modules.plugin.logger')
    def test_inner_request_post_with_json(self, mock_logger, mock_requests, mock_app):
        """Test POST request with JSON data"""
        mock_app.config = self.mock_app_config
        mock_response = Mock()
        mock_response.json.return_value = {'created': True}
        mock_requests.post.return_value = mock_response
        
        plugin = Plugin()
        json_data = {'key': 'value'}
        result = plugin.inner_request('POST', 'http://example.com', json=json_data)
        
        self.assertEqual(result, mock_response)
        mock_requests.post.assert_called_once()
        call_args = mock_requests.post.call_args[1]
        self.assertEqual(call_args['json'], json_data)

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.logger')
    @patch('application.modules.plugin.time')
    @patch('builtins.print')
    def test_inner_request_with_retries(self, mock_print, mock_time, mock_logger, mock_app):
        """Test request with retry logic"""
        mock_app.config = self.mock_app_config
        
        with patch('application.modules.plugin.requests') as mock_requests:
            # Set up the actual exception classes
            mock_requests.exceptions = requests.exceptions
            
            # Create a proper mock response that can be JSON serialized
            mock_response = Mock()
            mock_response.json.return_value = {'status': 'success'}
            mock_response.text = 'Success response'
            
            mock_requests.get.side_effect = [
                requests.exceptions.Timeout("Timeout occurred"),
                requests.exceptions.ConnectionError("Connection failed"),
                mock_response  # Success on third try
            ]
            
            plugin = Plugin()
            result = plugin.inner_request('GET', 'http://example.com')
            
            self.assertEqual(mock_requests.get.call_count, 3)
            self.assertEqual(mock_time.sleep.call_count, 2)
            # Verify print statements for retry attempts
            self.assertEqual(mock_print.call_count, 4)  # 2 failure messages + 2 timeout messages

    @patch('application.modules.plugin.app')
    @patch('builtins.print')
    def test_inner_request_max_retries_exceeded(self, mock_print, mock_app):
        """Test request failing after max retries"""
        mock_app.config = self.mock_app_config
        
        with patch('application.modules.plugin.requests') as mock_requests:
            # Set up the actual exception classes
            mock_requests.exceptions = requests.exceptions
            mock_requests.get.side_effect = requests.exceptions.Timeout("Max retries exceeded")
            
            plugin = Plugin()
            with self.assertRaises(requests.exceptions.Timeout):
                plugin.inner_request('GET', 'http://example.com')

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.logger')
    def test_inner_request_dry_run(self, mock_logger, mock_app):
        """Test request in dry run mode"""
        mock_app.config = self.mock_app_config
        
        plugin = Plugin()
        plugin.dry_run = True
        result = plugin.inner_request('POST', 'http://example.com', data={'test': 'data'})
        
        # Should return namedtuple mock response
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers, {})

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.CustomAttributeRule')
    @patch('application.modules.plugin.CustomAttributeRuleModel')
    def test_init_custom_attributes(self, mock_rule_model, mock_rule_class, mock_app):
        """Test custom attributes initialization"""
        mock_app.config = self.mock_app_config
        mock_rules = [Mock(), Mock()]
        mock_rule_model.objects.return_value.order_by.return_value = mock_rules
        mock_rule_instance = Mock()
        mock_rule_class.return_value = mock_rule_instance
        
        plugin = Plugin()
        plugin.debug = True
        plugin.init_custom_attributes()
        
        self.assertEqual(plugin.custom_attributes, mock_rule_instance)
        self.assertTrue(plugin.custom_attributes.debug)
        self.assertEqual(plugin.custom_attributes.rules, mock_rules)

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.logger')
    def test_get_attributes_with_cache_hit(self, mock_logger, mock_app):
        """Test get_attributes with cache hit"""
        mock_app.config = self.mock_app_config
        
        # Mock database host
        mock_host = Mock()
        mock_host.hostname = 'test-host'
        mock_host.cache = {
            'test_cache_hostattribute': {
                'attributes': {
                    'all': {'attr1': 'value1'},
                    'filtered': {'attr2': 'value2'}
                }
            }
        }
        
        plugin = Plugin()
        result = plugin.get_attributes(mock_host, 'test_cache')
        
        expected = {
            'all': {'attr1': 'value1'},
            'filtered': {'attr2': 'value2'}
        }
        self.assertEqual(result, expected)

    @patch('application.modules.plugin.app')
    def test_get_attributes_ignore_host(self, mock_app):
        """Test get_attributes when host should be ignored"""
        mock_app.config = self.mock_app_config
        
        mock_host = Mock()
        mock_host.hostname = 'test-host'
        mock_host.cache = {
            'test_cache_hostattribute': {
                'attributes': {
                    'all': {'attr1': 'value1'},
                    'filtered': {'ignore_host': True}
                }
            }
        }
        
        plugin = Plugin()
        result = plugin.get_attributes(mock_host, 'test_cache')
        
        self.assertFalse(result)

    @patch('application.modules.plugin.app')
    def test_get_host_data(self, mock_app):
        """Test get_host_data method"""
        mock_app.config = self.mock_app_config
        
        mock_host = Mock()
        mock_attributes = {'attr1': 'value1'}
        mock_actions = Mock()
        mock_actions.get_outcomes.return_value = {'action1': 'result1'}
        
        plugin = Plugin()
        plugin.actions = mock_actions
        result = plugin.get_host_data(mock_host, mock_attributes)
        
        self.assertEqual(result, {'action1': 'result1'})
        mock_actions.get_outcomes.assert_called_once_with(mock_host, mock_attributes)

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.Host')
    @patch('application.modules.plugin.attribute_table')
    @patch('application.modules.plugin.cc')
    @patch('builtins.print')
    def test_debug_rules_host_not_found(self, mock_print, mock_cc, mock_attr_table, mock_host, mock_app):
        """Test debug_rules when host is not found"""
        mock_app.config = self.mock_app_config
        mock_host.objects.get.side_effect = DoesNotExist()
        mock_cc.FAIL = '\033[91m'
        mock_cc.ENDC = '\033[0m'
        
        plugin = Plugin()
        # Add the missing actions attribute
        plugin.actions = Mock()
        plugin.debug_rules('nonexistent-host', 'test-model')

        mock_print.assert_called_with('\033[91mHost not Found\033[0m')

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.Host')
    @patch('application.modules.plugin.attribute_table')
    @patch('application.modules.plugin.cc')
    @patch('builtins.print')
    def test_debug_rules_host_ignored(self, mock_print, mock_cc, mock_attr_table, mock_host, mock_app):
        """Test debug_rules when host is ignored"""
        mock_app.config = self.mock_app_config
        mock_host_obj = Mock()
        mock_host_obj.cache = {}
        mock_host.objects.get.return_value = mock_host_obj
        mock_cc.FAIL = '\033[91m'
        mock_cc.ENDC = '\033[0m'

        plugin = Plugin()
        plugin.actions = Mock()

        # Mock get_attributes to return False (ignored host)
        with patch.object(plugin, 'get_attributes', return_value=False):
            plugin.debug_rules('test-host', 'test-model')

        mock_print.assert_called_with('\033[91mTHIS HOST IS IGNORED BY RULE\033[0m')

    def test_get_unique_id(self):
        """Test get_unique_id static method"""
        with patch('application.modules.plugin.uuid.uuid1') as mock_uuid:
            mock_uuid.return_value = 'test-uuid-123'

            result = Plugin.get_unique_id()

            self.assertEqual(result, 'test-uuid-123')
            mock_uuid.assert_called_once()

    @patch('application.modules.plugin.app')
    def test_save_requests_functionality(self, mock_app):
        """Test save_requests file writing"""
        mock_app.config = self.mock_app_config
        
        plugin = Plugin()
        plugin.save_requests = '/tmp/test_requests.log'
        
        with patch('builtins.open', create=True) as mock_open:
            mock_file = Mock()
            mock_open.return_value = mock_file
            
            with patch('application.modules.plugin.requests.get') as mock_get:
                # Create a proper response mock that can be JSON serialized
                mock_response = Mock()
                mock_response.json.return_value = {'test': 'response'}
                mock_get.return_value = mock_response
                
                plugin.inner_request('GET', 'http://example.com')
            
            mock_open.assert_called_with('/tmp/test_requests.log', 'a', encoding='utf-8')
            mock_file.write.assert_called_once()
            # Verify that something was written (the exact format may vary)
            write_call_args = mock_file.write.call_args[0][0]
            self.assertIn('get||http://example.com||', write_call_args)

    @patch('application.modules.plugin.app')
    def test_ssl_verification_settings(self, mock_app):
        """Test SSL verification configuration"""
        # Test default case (no SSL errors disabled, no account)
        mock_app.config = self.mock_app_config
        
        with patch('application.modules.plugin.atexit'):
            plugin = Plugin()
            self.assertTrue(plugin.verify)
        
        # Test with DISABLE_SSL_ERRORS = True (global override)
        mock_app.config = {**self.mock_app_config, 'DISABLE_SSL_ERRORS': True}
        
        with patch('application.modules.plugin.atexit'):
            plugin = Plugin()
            # When DISABLE_SSL_ERRORS is True, verify should be False
            self.assertFalse(plugin.verify)
        
        # Test with account that has verify_cert setting
        mock_app.config = self.mock_app_config  # Reset to default
        with patch('application.modules.plugin.get_account') as mock_get_account, \
             patch('application.modules.plugin.atexit'):
            mock_get_account.return_value = {
                'name': 'test',
                '_id': '123',
                'verify_cert': False  # Account setting
            }
            plugin = Plugin(account='test')
            # Account's verify_cert setting should be used
            self.assertFalse(plugin.verify)


if __name__ == '__main__':
    # Run tests when script is executed directly
    # Usage: python tests/test_plugin.py
    unittest.main(verbosity=2)
