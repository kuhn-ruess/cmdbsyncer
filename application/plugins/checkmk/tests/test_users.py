"""
Unit tests for checkmk users module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.users import CheckmkUserSync
from tests import base_mock_init


class TestCheckmkUserSync(unittest.TestCase):
    """Tests for CheckmkUserSync"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param)

        self.init_patcher = patch(
            'application.plugins.checkmk.users.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.sync = CheckmkUserSync()

    def tearDown(self):
        self.init_patcher.stop()

    def _make_user(self, **overrides):
        defaults = {
            'user_id': 'testuser',
            'full_name': 'Test User',
            'password': 'secret',
            'disable_login': False,
            'email': 'test@example.com',
            'pager_address': '',
            'roles': ['user'],
            'contact_groups': ['all'],
            'remove_if_found': False,
            'overwrite_password': False,
            'disabled': False,
        }
        defaults.update(overrides)
        user = Mock()
        for key, val in defaults.items():
            setattr(user, key, val)
        return user

    @patch('application.plugins.checkmk.users.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_a_never_filled_field_is_sent_empty_not_null(self, mock_print,
                                                         mock_mngmt):
        # Checkmk answers "pager address may not be null" for every one of
        # these, and a field nobody ever filled in is None on the document
        user = self._make_user(pager_address=None, email=None,
                               disable_login=None, roles=None,
                               contact_groups=None, full_name=None)
        mock_mngmt.objects.return_value = [user]

        with patch.object(self.sync, 'request') as mock_req:
            mock_req.side_effect = [({}, {'status_code': 404}),
                                    ({'id': 'testuser'}, {})]
            self.sync.export_users()

        sent = mock_req.call_args_list[1][1]['data']
        self.assertEqual(sent['pager_address'], '')
        self.assertEqual(sent['contact_options']['email'], '')
        self.assertEqual(sent['disable_login'], False)
        self.assertEqual(sent['roles'], [])
        self.assertEqual(sent['contactgroups'], [])
        # A user without a full name is still a user Checkmk accepts
        self.assertEqual(sent['fullname'], 'testuser')

    @patch('application.plugins.checkmk.users.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_an_empty_field_is_not_a_change(self, mock_print, mock_mngmt):
        # Checkmk answers with the empty value, so a None on our side used
        # to look different on every run and rewrote the user each time
        user = self._make_user(pager_address=None, email=None)
        mock_mngmt.objects.return_value = [user]
        cmk_side = {
            'fullname': 'Test User', 'disable_login': False,
            'pager_address': '', 'contactgroups': ['all'],
            'roles': ['user'], 'contact_options': {'email': ''},
        }

        with patch.object(self.sync, 'request') as mock_req:
            mock_req.side_effect = [
                ({'extensions': cmk_side}, {'ETag': 'x'}),
            ]
            self.sync.export_users()

        # Only the GET happened, nothing was written back
        self.assertEqual(mock_req.call_count, 1)

    @patch('application.plugins.checkmk.users.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_export_users_creates_new(self, mock_print, mock_mngmt):
        user = self._make_user()
        mock_mngmt.objects.return_value = [user]

        with patch.object(self.sync, 'request') as mock_req:
            # First call: GET returns empty (user not found)
            # Second call: POST creates user
            mock_req.side_effect = [
                ({}, {'status_code': 404}),
                ({'id': 'testuser'}, {}),
            ]
            self.sync.export_users()

        self.assertEqual(mock_req.call_count, 2)
        # Second call should be POST
        self.assertEqual(mock_req.call_args_list[1][1]['method'], 'POST')

    @patch('application.plugins.checkmk.users.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_export_users_skip_create_if_remove_flag(self, mock_print, mock_mngmt):
        user = self._make_user(remove_if_found=True)
        mock_mngmt.objects.return_value = [user]

        with patch.object(self.sync, 'request') as mock_req:
            mock_req.return_value = ({}, {'status_code': 404})
            self.sync.export_users()

        # Only the GET request, no POST
        self.assertEqual(mock_req.call_count, 1)

    @patch('application.plugins.checkmk.users.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_export_users_deletes_when_remove_flag(self, mock_print, mock_mngmt):
        user = self._make_user(remove_if_found=True)
        mock_mngmt.objects.return_value = [user]

        cmk_response = {
            'extensions': {
                'fullname': 'Test User',
                'disable_login': False,
                'pager_address': '',
                'contactgroups': ['all'],
                'roles': ['user'],
                'contact_options': {'email': 'test@example.com'},
            }
        }

        with patch.object(self.sync, 'request') as mock_req:
            mock_req.side_effect = [
                (cmk_response, {'ETag': 'abc'}),
                (None, {}),
            ]
            self.sync.export_users()

        # Second call should be DELETE
        self.assertEqual(mock_req.call_args_list[1][1]['method'], 'DELETE')

    @patch('application.plugins.checkmk.users.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_export_users_updates_on_change(self, mock_print, mock_mngmt):
        user = self._make_user(full_name='New Name')
        mock_mngmt.objects.return_value = [user]

        cmk_response = {
            'extensions': {
                'fullname': 'Old Name',
                'disable_login': False,
                'pager_address': '',
                'contactgroups': ['all'],
                'roles': ['user'],
                'contact_options': {'email': 'test@example.com'},
            }
        }

        with patch.object(self.sync, 'request') as mock_req:
            mock_req.side_effect = [
                (cmk_response, {'ETag': 'abc'}),
                (None, {}),
            ]
            self.sync.export_users()

        # Second call should be PUT with if-match header
        self.assertEqual(mock_req.call_args_list[1][1]['method'], 'PUT')
        self.assertIn('if-match',
                       mock_req.call_args_list[1][1]['additional_header'])

    @patch('application.plugins.checkmk.users.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_export_users_no_change_no_update(self, mock_print, mock_mngmt):
        user = self._make_user()
        mock_mngmt.objects.return_value = [user]

        cmk_response = {
            'extensions': {
                'fullname': 'Test User',
                'disable_login': False,
                'pager_address': '',
                'contactgroups': ['all'],
                'roles': ['user'],
                'contact_options': {'email': 'test@example.com'},
            }
        }

        with patch.object(self.sync, 'request') as mock_req:
            mock_req.return_value = (cmk_response, {'ETag': 'abc'})
            self.sync.export_users()

        # Only the GET, no PUT
        self.assertEqual(mock_req.call_count, 1)

    @patch('application.plugins.checkmk.users.CheckmkUserMngmt')
    @patch('builtins.print')
    def test_export_users_overwrite_password(self, mock_print, mock_mngmt):
        user = self._make_user(overwrite_password=True)
        mock_mngmt.objects.return_value = [user]

        cmk_response = {
            'extensions': {
                'fullname': 'Test User',
                'disable_login': False,
                'pager_address': '',
                'contactgroups': ['all'],
                'roles': ['user'],
                'contact_options': {'email': 'test@example.com'},
            }
        }

        with patch.object(self.sync, 'request') as mock_req:
            mock_req.side_effect = [
                (cmk_response, {'ETag': 'abc'}),
                (None, {}),
            ]
            self.sync.export_users()

        # Should still PUT because overwrite_password is True
        self.assertEqual(mock_req.call_count, 2)
        call_data = mock_req.call_args_list[1][1]['data']
        self.assertIn('auth_option', call_data)


if __name__ == '__main__':
    unittest.main(verbosity=2)
