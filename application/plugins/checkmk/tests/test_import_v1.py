"""
Unit tests for checkmk import_v1 module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from mongoengine.errors import DoesNotExist
from application.plugins.checkmk.import_v1 import ImportCheckmk1


class TestImportCheckmk1(unittest.TestCase):
    """Tests for ImportCheckmk1"""

    def setUp(self):
        self.config = {
            '_id': 'abc123',
            'address': 'https://cmk.example.com',
            'username': 'automation',
            'password': 'secret',
        }
        with patch('application.plugins.checkmk.import_v1.log'):
            self.importer = ImportCheckmk1(self.config)

    def test_init_sets_account_id(self):
        self.assertEqual(self.importer.account_id, 'abc123')

    @patch('application.plugins.checkmk.import_v1.requests')
    def test_request_posts_to_webapi(self, mock_requests):
        mock_response = Mock()
        mock_response.text = "{'result': 'ok'}"
        mock_requests.post.return_value = mock_response

        result = self.importer.request('get_all_hosts', {})

        self.assertEqual(result, {'result': 'ok'})
        mock_requests.post.assert_called_once()

    @patch('application.plugins.checkmk.import_v1.requests')
    def test_request_with_payload(self, mock_requests):
        mock_response = Mock()
        mock_response.text = "{'result': 'ok'}"
        mock_requests.post.return_value = mock_response

        result = self.importer.request('get_host', {'hostname': 'test'})

        self.assertEqual(result, {'result': 'ok'})

    @patch('application.plugins.checkmk.import_v1.Host')
    def test_run_creates_new_host(self, mock_host):
        mock_host.objects.get.side_effect = DoesNotExist()
        mock_new_host = Mock()
        mock_host.return_value = mock_new_host
        mock_new_host.set_account.return_value = True

        all_hosts = {'host1': {'attr': 'val'}}
        with patch.object(self.importer, 'request',
                          return_value={'result': all_hosts}):
            self.importer.run()

        mock_new_host.save.assert_called_once()
        self.assertEqual(mock_new_host.hostname, 'host1')

    @patch('application.plugins.checkmk.import_v1.Host')
    def test_run_updates_existing_host(self, mock_host):
        mock_existing = Mock()
        mock_host.objects.get.return_value = mock_existing
        mock_existing.set_account.return_value = True

        all_hosts = {'host1': {'attr': 'val'}}
        with patch.object(self.importer, 'request',
                          return_value={'result': all_hosts}):
            self.importer.run()

        mock_existing.add_log.assert_called_with('Found in Source')
        mock_existing.save.assert_called_once()

    @patch('application.plugins.checkmk.import_v1.Host')
    def test_run_skips_save_if_not_owned(self, mock_host):
        mock_existing = Mock()
        mock_host.objects.get.return_value = mock_existing
        mock_existing.set_account.return_value = False

        all_hosts = {'host1': {'attr': 'val'}}
        with patch.object(self.importer, 'request',
                          return_value={'result': all_hosts}):
            self.importer.run()

        mock_existing.save.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
