"""
Unit tests for the CMK2 base class
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch, MagicMock

import requests

from application.plugins.checkmk.cmk2 import (
    CmkException, CMK2, FALLBACK_CMK_VERSION)


class TestCmkException(unittest.TestCase):
    """Tests for CmkException"""

    def test_is_exception(self):
        with self.assertRaises(CmkException):
            raise CmkException("test error")

    def test_message(self):
        exc = CmkException("test error")
        self.assertEqual(str(exc), "test error")


class TestCMK2Request(unittest.TestCase):
    """Tests for CMK2.request method"""

    def setUp(self):
        def mock_init(self_param, account=False):
            self_param.config = {
                'address': 'https://cmk.example.com',
                'username': 'automation',
                'password': 'secret',
            }
            self_param.checkmk_version = '2.3.0'

        self.init_patcher = patch.object(CMK2, '__init__', mock_init)
        self.init_patcher.start()
        self.cmk = CMK2()

    def tearDown(self):
        self.init_patcher.stop()

    def test_strips_leading_slash_from_url(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'result': 'ok'}
        mock_response.headers = {'status_code': 200}

        with patch.object(self.cmk, 'inner_request',
                          return_value=mock_response) as mock_req:
            self.cmk.request('/version')

            mock_req.assert_called_once()
            call_url = mock_req.call_args[0][1]
            self.assertIn('check_mk/api/1.0/version', call_url)
            self.assertNotIn('//version', call_url)

    def test_200_returns_json_and_headers(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': 'value'}
        mock_response.headers = {'ETag': 'abc'}

        with patch.object(self.cmk, 'inner_request', return_value=mock_response):
            result_json, result_headers = self.cmk.request('version')

        self.assertEqual(result_json, {'data': 'value'})
        self.assertEqual(result_headers['ETag'], 'abc')
        self.assertEqual(result_headers['status_code'], 200)

    def test_204_returns_empty_dict(self):
        mock_response = Mock()
        mock_response.status_code = 204
        mock_response.json.return_value = {}
        mock_response.headers = {}

        with patch.object(self.cmk, 'inner_request', return_value=mock_response):
            result_json, result_headers = self.cmk.request('some/endpoint')

        self.assertEqual(result_json, {})
        self.assertEqual(result_headers['status_code'], 204)

    def test_404_returns_error(self):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.json.return_value = {'title': 'Not Found'}
        mock_response.headers = {}

        with patch.object(self.cmk, 'inner_request', return_value=mock_response):
            result_json, result_headers = self.cmk.request('missing')

        self.assertEqual(result_json, {})
        self.assertEqual(result_headers, {"error": "Object not found"})

    def test_non_200_whitelisted_error_returns_status(self):
        mock_response = Mock()
        mock_response.status_code = 409
        mock_response.json.return_value = {'title': 'Not Found'}
        mock_response.headers = {}

        with patch.object(self.cmk, 'inner_request', return_value=mock_response):
            result_json, result_headers = self.cmk.request('endpoint')

        self.assertEqual(result_json, {})
        self.assertEqual(result_headers['status_code'], 409)

    def test_non_200_unknown_error_raises(self):
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.json.return_value = {
            'title': 'Server Error',
            'detail': 'Something broke',
            'fields': None,
        }
        mock_response.headers = {}

        with patch.object(self.cmk, 'inner_request', return_value=mock_response):
            with self.assertRaises(CmkException):
                self.cmk.request('endpoint')

    def test_error_without_fields_has_no_trailing_none(self):
        """A missing `fields` must not append a literal "None" to the message"""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            'title': 'Some actions failed',
            'detail': 'The following were faulty and were skipped: myhost.',
            'fields': None,
        }
        mock_response.headers = {}

        with patch.object(self.cmk, 'inner_request', return_value=mock_response):
            with self.assertRaises(CmkException) as caught:
                self.cmk.request('endpoint')

        self.assertEqual(
            str(caught.exception),
            'Some actions failed The following were faulty and were skipped: myhost.')

    def test_error_with_fields_keeps_them_attached(self):
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            'title': 'Bad Request',
            'detail': 'These fields have problems: entries',
            'fields': {'entries': {'0': 'broken'}},
        }
        mock_response.headers = {}

        with patch.object(self.cmk, 'inner_request', return_value=mock_response):
            with self.assertRaises(CmkException) as caught:
                self.cmk.request('endpoint')

        self.assertEqual(
            str(caught.exception),
            "Bad Request These fields have problems: entries{'entries': {'0': 'broken'}}")

    def test_timeout_raises_cmk_exception(self):
        """A timeout must be a normal Checkmk error so the sync can continue"""
        with patch.object(self.cmk, 'inner_request',
                          side_effect=requests.exceptions.ReadTimeout("too slow")):
            with self.assertRaises(CmkException) as caught:
                self.cmk.request('endpoint', method='POST')

        self.assertIn('Timeout on POST', str(caught.exception))
        self.assertIn('request_timeout', str(caught.exception))

    def test_connection_error_raises_cmk_exception(self):
        with patch.object(self.cmk, 'inner_request', side_effect=ConnectionError("fail")):
            with self.assertRaises(CmkException):
                self.cmk.request('endpoint')

    def test_connection_reset_returns_error(self):
        with patch.object(self.cmk, 'inner_request',
                          side_effect=ConnectionResetError("reset")):
            result_json, result_headers = self.cmk.request('endpoint')

        self.assertEqual(result_json, {})
        self.assertEqual(result_headers, {"error": "Checkmk Connections broken"})

    def test_additional_header_merged(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.headers = {}

        with patch.object(self.cmk, 'inner_request', return_value=mock_response) as mock_req:
            self.cmk.request('endpoint', additional_header={'if-match': '*'})

        call_headers = mock_req.call_args[1]['headers']
        self.assertEqual(call_headers['if-match'], '*')

    def test_custom_api_version(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.headers = {}

        with patch.object(self.cmk, 'inner_request',
                          return_value=mock_response) as mock_req:
            self.cmk.request('endpoint', api_version="/")

            call_url = mock_req.call_args[0][1]
            self.assertIn('/endpoint', call_url)
            self.assertNotIn('api/1.0', call_url)


class TestCMK2OfflineInit(unittest.TestCase):
    """
    Read-only analyses run against the Syncer database alone. They must
    not need a reachable Checkmk, so the constructor can skip the version
    probe — the version only decides the shape of a rule condition.
    """

    def test_no_probe_means_no_request(self):
        with patch.object(CMK2, '_probe_checkmk_version') as probe, \
             patch('application.modules.plugin.Plugin.__init__',
                   lambda self_param, account=False: None):
            sync = CMK2(probe_version=False)
        probe.assert_not_called()
        self.assertEqual(sync.checkmk_version, FALLBACK_CMK_VERSION)

    def test_the_account_version_wins_over_the_fallback(self):
        def fake_plugin_init(self_param, account=False):
            self_param.config = {'checkmk_version': '2.2.0p1'}
        with patch.object(CMK2, '_probe_checkmk_version') as probe, \
             patch('application.modules.plugin.Plugin.__init__',
                   fake_plugin_init):
            sync = CMK2(probe_version=False)
        probe.assert_not_called()
        self.assertEqual(sync.checkmk_version, '2.2.0p1')

    def test_the_probe_still_runs_by_default(self):
        def fake_plugin_init(self_param, account=False):
            self_param.config = {'address': 'https://cmk.example.com'}
        with patch.object(CMK2, '_probe_checkmk_version',
                          return_value='2.4.0') as probe, \
             patch('application.modules.plugin.Plugin.__init__',
                   fake_plugin_init):
            sync = CMK2()
        probe.assert_called_once()
        self.assertEqual(sync.checkmk_version, '2.4.0')


class TestCMK2FetchFolders(unittest.TestCase):
    """Tests for fetch_checkmk_folders"""

    def setUp(self):
        def mock_init(self_param, account=False):
            self_param.config = {
                'address': 'https://cmk.example.com',
                'username': 'automation',
                'password': 'secret',
            }
            self_param.checkmk_version = '2.3.0'
            self_param.existing_folders = []
            self_param.existing_folders_attributes = {}

        self.init_patcher = patch.object(CMK2, '__init__', mock_init)
        self.init_patcher.start()
        self.cmk = CMK2()

    def tearDown(self):
        self.init_patcher.stop()

    @patch('application.plugins.checkmk.cmk2.Progress')
    def test_fetch_populates_folders(self, mock_progress_cls):
        mock_progress = MagicMock()
        mock_progress_cls.return_value.__enter__ = Mock(return_value=mock_progress)
        mock_progress_cls.return_value.__exit__ = Mock(return_value=False)

        api_response = ({
            'value': [
                {
                    'title': 'Folder1',
                    'extensions': {
                        'path': '/folder1',
                        'attributes': {'tag_agent': 'cmk-agent'}
                    }
                },
                {
                    'title': 'Folder2',
                    'extensions': {
                        'path': '/folder2',
                        'attributes': {}
                    }
                }
            ]
        }, {})

        with patch.object(self.cmk, 'request', return_value=api_response):
            self.cmk.fetch_checkmk_folders()

        self.assertIn('/folder1', self.cmk.existing_folders)
        self.assertIn('/folder2', self.cmk.existing_folders)
        self.assertEqual(
            self.cmk.existing_folders_attributes['/folder1']['title'], 'Folder1')

    @patch('application.plugins.checkmk.cmk2.Progress')
    def test_fetch_empty_response_raises(self, mock_progress_cls):
        mock_progress = MagicMock()
        mock_progress_cls.return_value.__enter__ = Mock(return_value=mock_progress)
        mock_progress_cls.return_value.__exit__ = Mock(return_value=False)

        with patch.object(self.cmk, 'request', return_value=({}, {})):
            with self.assertRaises(CmkException):
                self.cmk.fetch_checkmk_folders()


class TestCMK2GetHostsOfFolder(unittest.TestCase):
    """Tests for get_hosts_of_folder"""

    def setUp(self):
        def mock_init(self_param, account=False):
            self_param.config = {
                'address': 'https://cmk.example.com',
                'username': 'automation',
                'password': 'secret',
            }
            self_param.checkmk_version = '2.3.0'
            self_param.checkmk_hosts = {}

        self.init_patcher = patch.object(CMK2, '__init__', mock_init)
        self.init_patcher.start()
        self.cmk = CMK2()

    def tearDown(self):
        self.init_patcher.stop()

    def test_replaces_slashes_with_tilde(self):
        api_response = ({
            'value': [
                {
                    'id': 'host1',
                    'data': 'x',
                    'extensions': {
                        'attributes': {'labels': {'a': 'b'}},
                        'folder': '/servers',
                        'is_cluster': True,
                        'cluster_nodes': ['n1'],
                        'unused': 'drop-me',
                    }
                },
            ]
        }, {})

        with patch.object(self.cmk, 'request', return_value=api_response) as mock_req:
            result = self.cmk.get_hosts_of_folder('/a/b', '')

        call_url = mock_req.call_args[0][0]
        self.assertIn('~a~b', call_url)
        self.assertEqual(
            result['host1'],
            {
                'extensions': {
                    'attributes': {'labels': {'a': 'b'}},
                    'folder': '/servers',
                    'is_cluster': True,
                    'cluster_nodes': ['n1'],
                }
            }
        )


class TestCMK2FetchHosts(unittest.TestCase):
    """Tests for compact host fetching."""

    def setUp(self):
        def mock_init(self_param, account=False):
            self_param.config = {
                'address': 'https://cmk.example.com',
                'username': 'automation',
                'password': 'secret',
            }
            self_param.checkmk_version = '2.3.0'
            self_param.checkmk_hosts = {}
            self_param.existing_folders = ['/a', '/b']

        self.init_patcher = patch.object(CMK2, '__init__', mock_init)
        self.init_patcher.start()
        self.cmk = CMK2()

    def tearDown(self):
        self.init_patcher.stop()

    @patch('application.plugins.checkmk.cmk2.Progress')
    def test_fetch_all_checkmk_hosts_compacts_host_payload(self, mock_progress_cls):
        mock_progress = MagicMock()
        mock_progress_cls.return_value.__enter__ = Mock(return_value=mock_progress)
        mock_progress_cls.return_value.__exit__ = Mock(return_value=False)

        api_response = ({
            'value': [
                {
                    'id': 'host1',
                    'extensions': {
                        'attributes': {'labels': {'a': 'b'}},
                        'folder': '/servers',
                        'is_cluster': False,
                        'cluster_nodes': [],
                        'unused': {'large': 'payload'},
                    }
                }
            ]
        }, {})

        with patch.object(self.cmk, 'request', return_value=api_response):
            self.cmk.fetch_all_checkmk_hosts()

        self.assertEqual(
            self.cmk.checkmk_hosts['host1'],
            {
                'extensions': {
                    'attributes': {'labels': {'a': 'b'}},
                    'folder': '/servers',
                    'is_cluster': False,
                    'cluster_nodes': [],
                }
            }
        )

    @patch('application.plugins.checkmk.cmk2.Progress')
    def test_fetch_all_checkmk_hosts_preserves_effective_attributes(self, mock_progress_cls):
        # Inventorize requests ?effective_attributes=true and reads
        # host['extensions']['effective_attributes']. The compaction must
        # carry it through when present, otherwise inventorize KeyErrors.
        mock_progress = MagicMock()
        mock_progress_cls.return_value.__enter__ = Mock(return_value=mock_progress)
        mock_progress_cls.return_value.__exit__ = Mock(return_value=False)

        api_response = ({
            'value': [
                {
                    'id': 'host1',
                    'extensions': {
                        'attributes': {'labels': {'a': 'b'}},
                        'effective_attributes': {
                            'tag_agent': 'cmk-agent',
                            'labels': {'a': 'b', 'inherited': 'yes'},
                        },
                        'folder': '/servers',
                        'is_cluster': False,
                        'cluster_nodes': [],
                    }
                }
            ]
        }, {})

        with patch.object(self.cmk, 'request', return_value=api_response):
            self.cmk.fetch_all_checkmk_hosts()

        host_ext = self.cmk.checkmk_hosts['host1']['extensions']
        self.assertEqual(
            host_ext['effective_attributes'],
            {'tag_agent': 'cmk-agent', 'labels': {'a': 'b', 'inherited': 'yes'}},
        )

    @patch('application.plugins.checkmk.cmk2.multiprocessing')
    @patch('application.plugins.checkmk.cmk2.Progress')
    def test_fetch_checkmk_host_by_folder_collects_plain_results(self, mock_progress_cls, mock_mp):
        mock_progress = MagicMock()
        mock_progress_cls.return_value.__enter__ = Mock(return_value=mock_progress)
        mock_progress_cls.return_value.__exit__ = Mock(return_value=False)
        mock_pool = Mock()
        mock_mp.Pool.return_value.__enter__.return_value = mock_pool

        task1 = Mock()
        task1.get.return_value = {
            'host1': {'extensions': {
                'attributes': {}, 'folder': '/a', 'is_cluster': False, 'cluster_nodes': [],
            }}
        }
        task2 = Mock()
        task2.get.return_value = {
            'host2': {'extensions': {
                'attributes': {}, 'folder': '/b', 'is_cluster': False, 'cluster_nodes': [],
            }}
        }
        mock_pool.apply_async.side_effect = [task1, task2]

        self.cmk._fetch_checkmk_host_by_folder()

        self.assertIn('host1', self.cmk.checkmk_hosts)
        self.assertIn('host2', self.cmk.checkmk_hosts)
        self.assertEqual(mock_pool.apply_async.call_count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
