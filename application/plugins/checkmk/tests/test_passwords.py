"""
Unit tests for checkmk passwords module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import MagicMock, Mock, patch

from application.plugins.checkmk.passwords import CheckmkPasswordSync
from tests import base_mock_init


class TestCheckmkPasswordSync(unittest.TestCase):
    """Tests for CheckmkPasswordSync"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param,
                           console=Mock(), current_password_ids=[])

        self.init_patcher = patch(
            'application.plugins.checkmk.passwords.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.sync = CheckmkPasswordSync()

    def tearDown(self):
        self.init_patcher.stop()

    def test_get_current_passwords(self):
        response = ({
            'value': [
                {'id': 'pw1'},
                {'id': 'pw2'},
            ]
        }, {})

        with patch.object(self.sync, 'request', return_value=response):
            self.sync.get_current_passwords()

        self.assertEqual(self.sync.current_password_ids, ['pw1', 'pw2'])

    def test_build_payload_basic(self):
        password = Mock()
        password.__getitem__ = lambda self, key: {
            'id': 'abc123',
            'title': 'My Password',
            'comment': 'A test password',
            'owner': 'admin',
            'documentation_url': '',
        }[key]
        password.get_password.return_value = 'secret123'
        password.shared = ['all']

        payload = self.sync.build_payload(password)

        self.assertEqual(payload['ident'], 'cmdbsyncer_abc123')
        self.assertEqual(payload['title'], 'My Password')
        self.assertEqual(payload['password'], 'secret123')
        self.assertEqual(payload['owner'], 'admin')
        self.assertEqual(payload['shared'], ['all'])
        self.assertNotIn('documentation_url', payload)

    def test_build_payload_with_doc_url(self):
        password = Mock()
        password.__getitem__ = lambda self, key: {
            'id': 'abc123',
            'title': 'My Password',
            'comment': '',
            'owner': 'admin',
            'documentation_url': 'https://example.com',
        }[key]
        password.get_password.return_value = 'secret'
        password.shared = []

        payload = self.sync.build_payload(password)
        self.assertEqual(payload['documentation_url'], 'https://example.com')

    def test_create_password(self):
        password = Mock()
        password.__getitem__ = lambda self, key: {
            'id': 'pw1', 'title': 'Test', 'comment': '',
            'owner': 'admin', 'documentation_url': '', 'name': 'TestPW',
        }[key]
        password.get_password.return_value = 'secret'
        password.shared = []

        with patch.object(self.sync, 'request') as mock_req, \
             patch.object(self.sync, 'build_payload',
                          return_value={'ident': 'cmdbsyncer_pw1'}):
            mock_req.return_value = (None, {})
            self.sync.create_password(password)

        mock_req.assert_called_once()
        self.assertEqual(mock_req.call_args[1]['method'], 'POST')

    def test_update_password(self):
        password = Mock()
        password.__getitem__ = lambda self, key: {
            'id': 'pw1', 'title': 'Test', 'comment': '',
            'owner': 'admin', 'documentation_url': '', 'name': 'TestPW',
        }[key]
        password.get_password.return_value = 'secret'
        password.shared = []

        with patch.object(self.sync, 'request') as mock_req, \
             patch.object(self.sync, 'build_payload',
                          return_value={'ident': 'cmdbsyncer_pw1', 'title': 'Test'}):
            mock_req.return_value = (None, {})
            self.sync.update_password(password)

        mock_req.assert_called_once()
        self.assertEqual(mock_req.call_args[1]['method'], 'PUT')
        # ident should be removed from payload for update
        call_data = mock_req.call_args[1]['data']
        self.assertNotIn('ident', call_data)

    def test_update_password_keeps_ident_on_payload(self):
        # A caller-provided payload must not be mutated (ident stays intact
        # so the shared hash/id stay usable after update_password ran).
        password = Mock()
        password.__getitem__ = lambda self, key: {'name': 'TestPW'}[key]
        payload = {'ident': 'cmdbsyncer_pw1', 'title': 'Test'}

        with patch.object(self.sync, 'request') as mock_req:
            mock_req.return_value = (None, {})
            self.sync.update_password(password, payload)

        self.assertIn('ident', payload)
        self.assertNotIn('ident', mock_req.call_args[1]['data'])

    def _password_doc(self, last_export_hash=None):
        password = Mock()
        password.__getitem__ = lambda self, key: {
            'id': 'pw1', 'title': 'Test', 'comment': '',
            'owner': 'admin', 'documentation_url': '', 'name': 'TestPW',
        }[key]
        password.get_password.return_value = 'secret'
        password.shared = []
        password.last_export_hash = last_export_hash
        return password

    @staticmethod
    def _queryset(password):
        queryset = MagicMock()
        queryset.count.return_value = 1
        queryset.__iter__.return_value = iter([password])
        return queryset

    @patch('application.plugins.checkmk.passwords.Progress')
    @patch('application.plugins.checkmk.passwords.CheckmkPassword')
    def test_export_skips_unchanged_password(self, mock_model, mock_progress):
        password = self._password_doc()
        # Precompute the hash the export will produce, mark it as exported.
        password.last_export_hash = self.sync.payload_hash(
            self.sync.build_payload(password))
        mock_model.objects.return_value = self._queryset(password)
        self.sync.current_password_ids = ['cmdbsyncer_pw1']

        with patch.object(self.sync, 'get_current_passwords'), \
             patch.object(self.sync, 'request') as mock_req:
            self.sync.export_passwords()

        # No create/update request, and the doc is not re-saved.
        mock_req.assert_not_called()
        password.save.assert_not_called()

    @patch('application.plugins.checkmk.passwords.Progress')
    @patch('application.plugins.checkmk.passwords.CheckmkPassword')
    def test_export_updates_changed_password(self, mock_model, mock_progress):
        password = self._password_doc(last_export_hash='stale')
        mock_model.objects.return_value = self._queryset(password)
        self.sync.current_password_ids = ['cmdbsyncer_pw1']

        with patch.object(self.sync, 'get_current_passwords'), \
             patch.object(self.sync, 'request') as mock_req:
            mock_req.return_value = (None, {})
            self.sync.export_passwords()

        mock_req.assert_called_once()
        self.assertEqual(mock_req.call_args[1]['method'], 'PUT')
        # Fresh hash stored so the next run skips it.
        self.assertEqual(
            password.last_export_hash,
            self.sync.payload_hash(self.sync.build_payload(password)))
        password.save.assert_called_once()

    @patch('application.plugins.checkmk.passwords.Progress')
    @patch('application.plugins.checkmk.passwords.CheckmkPassword')
    def test_export_creates_missing_password(self, mock_model, mock_progress):
        password = self._password_doc()
        mock_model.objects.return_value = self._queryset(password)
        self.sync.current_password_ids = []

        with patch.object(self.sync, 'get_current_passwords'), \
             patch.object(self.sync, 'request') as mock_req:
            mock_req.return_value = (None, {})
            self.sync.export_passwords()

        mock_req.assert_called_once()
        self.assertEqual(mock_req.call_args[1]['method'], 'POST')
        password.save.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
