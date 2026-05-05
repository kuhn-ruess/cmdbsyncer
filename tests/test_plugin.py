"""
Unit tests for the Plugin base class
"""
# pylint: disable=missing-function-docstring,unused-argument,too-many-public-methods
import unittest
from unittest.mock import MagicMock, Mock, patch
import time

import requests
from mongoengine.errors import DoesNotExist

from application.modules.plugin import Plugin


# pylint: disable=protected-access
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
        mock_app.config = self.mock_app_config

        plugin = Plugin()

        self.assertIsNotNone(plugin.start_time)
        self.assertEqual(plugin.name, "Undefined")
        self.assertTrue(plugin.verify)
        self.assertFalse(plugin.dry_run)
        self.assertFalse(plugin.save_requests)
        registered = [c.args[0] for c in mock_atexit.register.call_args_list]
        self.assertIn(plugin.save_log, registered)
        self.assertIn(plugin._cleanup_resources, registered)
        mock_get_account.assert_not_called()

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.get_account')
    @patch('application.modules.plugin.atexit')
    def test_init_with_valid_account(self, _atexit, mock_get_account, mock_app):
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
        mock_app.config = self.mock_app_config
        mock_get_account.return_value = None

        with self.assertRaises(ValueError) as context:
            Plugin(account='invalid_account')

        self.assertEqual(str(context.exception), "Account Invalid or not found")

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.log')
    def test_save_log(self, mock_log, mock_app):
        mock_app.config = self.mock_app_config

        plugin = Plugin()
        plugin.name = "TestPlugin"
        plugin.source = "TestSource"

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
    def test_inner_request_get_success(self, _logger, mock_requests, mock_app):
        mock_app.config = self.mock_app_config
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'success'}
        mock_session = Mock()
        mock_session.request.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        plugin = Plugin()
        result = plugin.inner_request('GET', 'http://example.com')

        self.assertEqual(result, mock_response)
        mock_session.request.assert_called_once_with(
            'get',
            'http://example.com',
            verify=True,
            timeout=30,
        )

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.requests')
    @patch('application.modules.plugin.logger')
    def test_inner_request_post_with_json(self, _logger, mock_requests, mock_app):
        mock_app.config = self.mock_app_config
        mock_response = Mock()
        mock_response.json.return_value = {'created': True}
        mock_session = Mock()
        mock_session.request.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        plugin = Plugin()
        json_data = {'key': 'value'}
        result = plugin.inner_request(
            'POST', 'http://example.com', json=json_data
        )

        self.assertEqual(result, mock_response)
        mock_session.request.assert_called_once()
        call_args = mock_session.request.call_args[1]
        self.assertEqual(call_args['json'], json_data)

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.logger')
    @patch('application.modules.plugin.time')
    @patch('builtins.print')
    def test_inner_request_with_retries(
        self, mock_print, mock_time, _logger, mock_app
    ):
        mock_app.config = self.mock_app_config

        with patch('application.modules.plugin.requests') as mock_requests:
            # Set up the actual exception classes
            mock_requests.exceptions = requests.exceptions
            mock_session = Mock()
            mock_requests.Session.return_value = mock_session

            mock_response = Mock()
            mock_response.json.return_value = {'status': 'success'}
            mock_response.text = 'Success response'

            mock_session.request.side_effect = [
                requests.exceptions.Timeout("Timeout occurred"),
                requests.exceptions.ConnectionError("Connection failed"),
                mock_response  # Success on third try
            ]

            plugin = Plugin()
            plugin.inner_request('GET', 'http://example.com')

            self.assertEqual(mock_session.request.call_count, 3)
            self.assertEqual(mock_time.sleep.call_count, 2)
            self.assertEqual(mock_print.call_count, 4)

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.time')
    @patch('builtins.print')
    def test_inner_request_max_retries_exceeded(self, _print, _time, mock_app):
        mock_app.config = self.mock_app_config

        with patch('application.modules.plugin.requests') as mock_requests:
            mock_requests.exceptions = requests.exceptions
            mock_session = Mock()
            mock_session.request.side_effect = \
                requests.exceptions.Timeout("Max retries exceeded")
            mock_requests.Session.return_value = mock_session

            plugin = Plugin()
            with self.assertRaises(requests.exceptions.Timeout):
                plugin.inner_request('GET', 'http://example.com')

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.requests')
    @patch('application.modules.plugin.log')
    @patch('application.modules.plugin.logger')
    def test_cleanup_closes_http_session(self, _logger, _log, mock_requests, mock_app):
        mock_app.config = self.mock_app_config
        mock_session = Mock()
        mock_requests.exceptions = requests.exceptions
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'ok'}
        mock_session.request.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        plugin = Plugin()
        plugin.inner_request('GET', 'http://example.com')
        plugin._cleanup_resources()

        mock_session.close.assert_called_once()
        self.assertIsNone(plugin._http_session)

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.requests')
    @patch('application.modules.plugin.log')
    @patch('application.modules.plugin.logger')
    def test_cleanup_runs_on_half_built_plugin(
            self, _logger, _log, mock_requests, mock_app
    ):
        """Regression: a subclass __init__ that raises before
        _init_complete = True must still release the Session."""
        mock_app.config = self.mock_app_config
        mock_session = Mock()
        mock_requests.exceptions = requests.exceptions
        mock_session.request.return_value = Mock(json=lambda: {})
        mock_requests.Session.return_value = mock_session

        plugin = Plugin()
        plugin.inner_request('GET', 'http://example.com')
        plugin._init_complete = False  # simulate subclass init failure

        plugin._cleanup_resources()

        mock_session.close.assert_called_once()

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.logger')
    def test_inner_request_dry_run(self, _logger, mock_app):
        mock_app.config = self.mock_app_config

        plugin = Plugin()
        plugin.dry_run = True
        result = plugin.inner_request(
            'POST', 'http://example.com', data={'test': 'data'}
        )

        # Should return namedtuple mock response
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers, {})

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.CustomAttributeRule')
    @patch('application.modules.plugin.CustomAttributeRuleModel')
    def test_init_custom_attributes(
        self, mock_rule_model, mock_rule_class, mock_app
    ):
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
    def test_get_attributes_with_cache_hit(self, _logger, mock_app):
        mock_app.config = self.mock_app_config

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
    def test_get_attributes_deferred_cache_save(self, mock_app):
        mock_app.config = self.mock_app_config

        mock_host = Mock()
        mock_host.hostname = 'test-host'
        mock_host.cache = {}
        mock_host.labels = {'label1': 'value1'}
        mock_host.inventory = {'inv1': 'value2'}
        mock_host.cmdb_templates = []

        plugin = Plugin()
        plugin.custom_attributes = Mock()
        plugin.custom_attributes.get_outcomes.return_value = {'custom': 'x'}
        plugin.init_custom_attributes = Mock()
        plugin.rewrite = Mock()
        plugin.rewrite.get_outcomes.return_value = {'add_extra': 'y'}
        plugin.filter = Mock()
        plugin.filter.get_outcomes.return_value = {'filtered': 'z'}

        result = plugin.get_attributes(mock_host, 'test_cache', persist_cache=False)

        self.assertEqual(result['all']['custom'], 'x')
        self.assertEqual(result['all']['extra'], 'y')
        self.assertEqual(result['filtered'], {'filtered': 'z'})
        self.assertTrue(mock_host.cache['test_cache_hostattribute']['attributes'])
        mock_host.save.assert_not_called()
        self.assertTrue(getattr(mock_host, '_cache_dirty', False))
        plugin.custom_attributes.get_outcomes.assert_called_once()
        self.assertEqual(
            plugin.custom_attributes.get_outcomes.call_args.kwargs['persist_cache'], False,
        )
        self.assertEqual(
            plugin.rewrite.get_outcomes.call_args.kwargs['persist_cache'], False,
        )
        self.assertEqual(plugin.filter.get_outcomes.call_args.kwargs['persist_cache'], False)

    @patch('application.modules.plugin.render_jinja')
    @patch('application.modules.plugin.app')
    def test_get_attributes_renders_jinja_in_template_values(
            self, mock_app, mock_render):
        mock_app.config = self.mock_app_config
        mock_render.side_effect = (
            lambda value, **kwargs: f"rendered:{value}:{kwargs['HOSTNAME']}"
        )

        tmpl = Mock()
        tmpl.hostname = 'web-template'
        tmpl.labels = {
            'description': 'Server {{ HOSTNAME }}',
            'plain': 'no jinja here',
        }

        mock_host = Mock()
        mock_host.hostname = 'web01'
        mock_host.cache = {}
        mock_host.labels = {'environment': 'prod'}
        mock_host.inventory = {}
        mock_host.cmdb_templates = [tmpl]

        plugin = Plugin()
        plugin.custom_attributes = Mock()
        plugin.custom_attributes.get_outcomes.return_value = {}
        plugin.init_custom_attributes = Mock()
        plugin.rewrite = None
        plugin.filter = None

        result = plugin.get_attributes(mock_host, False)

        # Values containing `{{` are routed through render_jinja with
        # HOSTNAME plus the existing host attributes as context.
        self.assertEqual(
            result['all']['description'],
            'rendered:Server {{ HOSTNAME }}:web01',
        )
        # Plain strings without `{{` skip render_jinja entirely.
        self.assertEqual(result['all']['plain'], 'no jinja here')
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args.kwargs
        self.assertEqual(call_kwargs['HOSTNAME'], 'web01')
        self.assertEqual(call_kwargs['environment'], 'prod')

    @patch('application.modules.plugin.app')
    def test_get_host_data(self, mock_app):
        mock_app.config = self.mock_app_config

        mock_host = Mock()
        mock_attributes = {'attr1': 'value1'}
        mock_actions = Mock()
        mock_actions.get_outcomes.return_value = {'action1': 'result1'}

        plugin = Plugin()
        plugin.actions = mock_actions
        result = plugin.get_host_data(mock_host, mock_attributes)

        self.assertEqual(result, {'action1': 'result1'})
        mock_actions.get_outcomes.assert_called_once_with(
            mock_host, mock_attributes
        )

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.Host')
    @patch('application.modules.plugin.attribute_table')
    @patch('application.modules.plugin.cc')
    @patch('builtins.print')
    def test_debug_rules_host_not_found(
        self, mock_print, mock_cc, _attr_table, mock_host, mock_app
    ):
        mock_app.config = self.mock_app_config
        mock_host.objects.get.side_effect = DoesNotExist()
        mock_cc.FAIL = '\033[91m'
        mock_cc.ENDC = '\033[0m'

        plugin = Plugin()
        plugin.actions = Mock()
        plugin.debug_rules('nonexistent-host', 'test-model')

        mock_print.assert_called_with('\033[91mHost not Found\033[0m')

    @patch('application.modules.plugin.app')
    @patch('application.modules.plugin.Host')
    @patch('application.modules.plugin.attribute_table')
    @patch('application.modules.plugin.cc')
    @patch('builtins.print')
    def test_debug_rules_host_ignored(
        self, mock_print, mock_cc, _attr_table, mock_host, mock_app
    ):
        mock_app.config = self.mock_app_config
        mock_host_obj = Mock()
        mock_host_obj.cache = {}
        mock_host.objects.get.return_value = mock_host_obj
        mock_cc.FAIL = '\033[91m'
        mock_cc.ENDC = '\033[0m'

        plugin = Plugin()
        plugin.actions = Mock()

        with patch.object(plugin, 'get_attributes', return_value=False):
            plugin.debug_rules('test-host', 'test-model')

        mock_print.assert_called_with(
            '\033[91mTHIS HOST IS IGNORED BY RULE\033[0m'
        )

    def test_get_unique_id(self):
        with patch('application.modules.plugin.uuid.uuid1') as mock_uuid:
            mock_uuid.return_value = 'test-uuid-123'

            result = Plugin.get_unique_id()

            self.assertEqual(result, 'test-uuid-123')
            mock_uuid.assert_called_once()

    @patch('application.modules.plugin.app')
    def test_save_requests_functionality(self, mock_app):
        mock_app.config = self.mock_app_config

        plugin = Plugin()
        plugin.save_requests = '/tmp/test_requests.log'

        with patch('builtins.open', create=True) as mock_open:
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file

            with patch('application.modules.plugin.requests.Session') as mock_session_cls:
                mock_session = Mock()
                mock_response = Mock()
                mock_response.json.return_value = {'test': 'response'}
                mock_session.request.return_value = mock_response
                mock_session_cls.return_value = mock_session

                plugin.inner_request('GET', 'http://example.com')

            mock_open.assert_called_with(
                '/tmp/test_requests.log', 'a', encoding='utf-8'
            )
            mock_file.write.assert_called_once()
            write_call_args = mock_file.write.call_args[0][0]
            self.assertIn('get||http://example.com||', write_call_args)

    @patch('application.modules.plugin.app')
    def test_ssl_verification_settings(self, mock_app):
        mock_app.config = self.mock_app_config

        with patch('application.modules.plugin.atexit'):
            plugin = Plugin()
            self.assertTrue(plugin.verify)

        mock_app.config = {
            **self.mock_app_config, 'DISABLE_SSL_ERRORS': True
        }

        with patch('application.modules.plugin.atexit'):
            plugin = Plugin()
            self.assertFalse(plugin.verify)

        mock_app.config = self.mock_app_config
        with patch('application.modules.plugin.get_account') as mock_get, \
             patch('application.modules.plugin.atexit'):
            mock_get.return_value = {
                'name': 'test',
                '_id': '123',
                'verify_cert': False
            }
            plugin = Plugin(account='test')
            self.assertFalse(plugin.verify)


if __name__ == '__main__':
    unittest.main(verbosity=2)
