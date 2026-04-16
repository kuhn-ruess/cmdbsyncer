"""
Unit tests for checkmk import_v2 module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.import_v2 import DataGeter, import_hosts


class TestDataGeter(unittest.TestCase):
    """Tests for DataGeter"""

    def setUp(self):
        def mock_init(self_param, account=False):
            self_param.account_id = 'test_account'
            self_param.account_name = 'Test'
            self_param.config = {}
            self_param.log_details = []
            self_param.checkmk_version = '2.3.0'
            self_param.actions = Mock()
            self_param.debug = False

        self.init_patcher = patch(
            'application.plugins.checkmk.import_v2.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.getter = DataGeter()

    def tearDown(self):
        self.init_patcher.stop()

    @patch('application.plugins.checkmk.import_v2.Host')
    @patch('builtins.print')
    def test_run_imports_hosts(self, mock_print, mock_host):
        mock_host_obj = Mock()
        mock_host_obj.set_account.return_value = True
        mock_host.get_host.return_value = mock_host_obj

        api_response = ({
            'value': [
                {
                    'id': 'host1',
                    'extensions': {
                        'effective_attributes': {
                            'tag_agent': 'cmk-agent',
                            'labels': {'env': 'prod'},
                        }
                    }
                },
            ]
        }, {})

        with patch.object(self.getter, 'request', return_value=api_response):
            self.getter.run()

        mock_host.get_host.assert_called_once_with('host1')
        mock_host_obj.update_host.assert_called_once()
        mock_host_obj.save.assert_called_once()

    @patch('application.plugins.checkmk.import_v2.Host')
    @patch('builtins.print')
    def test_run_skips_filtered_hosts(self, mock_print, mock_host):
        self.getter.config = {'import_filter': 'test-, dev-'}

        api_response = ({
            'value': [
                {
                    'id': 'test-host1',
                    'extensions': {
                        'effective_attributes': {'labels': {}}
                    }
                },
                {
                    'id': 'prod-host1',
                    'extensions': {
                        'effective_attributes': {'labels': {}}
                    }
                },
            ]
        }, {})

        mock_host_obj = Mock()
        mock_host_obj.set_account.return_value = True
        mock_host.get_host.return_value = mock_host_obj

        with patch.object(self.getter, 'request', return_value=api_response):
            self.getter.run()

        # Only prod-host1 should be processed
        mock_host.get_host.assert_called_once_with('prod-host1')

    @patch('application.plugins.checkmk.import_v2.Host')
    @patch('builtins.print')
    def test_run_skips_if_not_owned(self, mock_print, mock_host):
        mock_host_obj = Mock()
        mock_host_obj.set_account.return_value = False
        mock_host.get_host.return_value = mock_host_obj

        api_response = ({
            'value': [
                {
                    'id': 'host1',
                    'extensions': {
                        'effective_attributes': {'labels': {}}
                    }
                },
            ]
        }, {})

        with patch.object(self.getter, 'request', return_value=api_response):
            self.getter.run()

        mock_host_obj.save.assert_not_called()

    @patch('builtins.print')
    def test_run_v22_url(self, mock_print):
        self.getter.checkmk_version = '2.2.0p1'

        with patch.object(self.getter, 'request') as mock_req:
            mock_req.return_value = ({'value': []}, {})
            self.getter.run()

        call_url = mock_req.call_args[0][0]
        self.assertNotIn('include_links', call_url)

    @patch('builtins.print')
    def test_run_v23_url(self, mock_print):
        self.getter.checkmk_version = '2.3.0'

        with patch.object(self.getter, 'request') as mock_req:
            mock_req.return_value = ({'value': []}, {})
            self.getter.run()

        call_url = mock_req.call_args[0][0]
        self.assertIn('include_links=false', call_url)


class TestImportHosts(unittest.TestCase):
    """Tests for import_hosts function"""

    @patch('application.plugins.checkmk.import_v2.DataGeter')
    def test_import_hosts_creates_and_runs(self, mock_getter_cls):
        mock_instance = Mock()
        mock_getter_cls.return_value = mock_instance

        import_hosts('test_account', debug=True)

        mock_getter_cls.assert_called_once_with('test_account')
        self.assertTrue(mock_instance.debug)
        mock_instance.run.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
