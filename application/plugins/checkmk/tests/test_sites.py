"""
Unit tests for checkmk sites module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.sites import CheckmkSites
from tests import base_mock_init


class TestCheckmkSites(unittest.TestCase):
    """Tests for CheckmkSites"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param)

        self.init_patcher = patch(
            'application.plugins.checkmk.sites.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.sync = CheckmkSites()

    def tearDown(self):
        self.init_patcher.stop()

    def test_get_sites(self):
        response = ({
            'value': [
                {'id': 'site1', 'extensions': {'basic_settings': {'site_id': 's1'}}},
                {'id': 'site2', 'extensions': {'basic_settings': {'site_id': 's2'}}},
            ]
        }, {})

        with patch.object(self.sync, 'request', return_value=response):
            result = self.sync.get_sites()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['id'], 'site1')

    @patch('application.plugins.checkmk.sites.Host')
    @patch('builtins.print')
    def test_import_sites(self, mock_print, mock_host):
        mock_syncer_obj = Mock()
        mock_host.get_host.return_value = mock_syncer_obj

        sites_data = [
            {
                'extensions': {
                    'basic_settings': {'site_id': 'site1', 'alias': 'Site 1'}
                }
            },
        ]

        with patch.object(self.sync, 'get_sites', return_value=sites_data):
            self.sync.import_sites()

        mock_host.get_host.assert_called_once_with('site1')
        mock_syncer_obj.update_host.assert_called_once()
        mock_syncer_obj.save.assert_called_once()
        self.assertTrue(mock_syncer_obj.is_object)
        self.assertEqual(mock_syncer_obj.object_type, 'cmk_site')


if __name__ == '__main__':
    unittest.main(verbosity=2)
