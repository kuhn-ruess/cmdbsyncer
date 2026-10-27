"""
Unit tests for the Checkmk LDAP Connection export
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
# pylint: disable=wrong-import-order,unused-import
import tests  # noqa: F401 — triggers MongoDB stub setup (must be first)
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from application.plugins.checkmk import ldap_connections
from application.plugins.checkmk.ldap_connections import (
    CheckmkLdapConnectionSync,
    build_payload,
    needs_update,
)
from tests import base_mock_init

ACCOUNT = {
    'address': 'ldaps://dc1.example.com',
    'username': 'CN=bind,DC=example,DC=com',
    'password': 'secret',
}


def _connection(**kwargs):
    """A connection with the model's defaults"""
    fields = {
        'connection_id': 'ldap_ad', 'description': None, 'comment': None,
        'ldap_account': 'ad', 'directory_type': 'active_directory_manual',
        'failover_servers': [], 'bind_secret': None, 'connection_suffix': None,
        'user_base_dn': 'OU=users,DC=example,DC=com', 'user_search_filter': None,
        'user_filter_group': None, 'user_id_attribute': None,
        'lower_user_ids': False, 'create_users': 'on_login',
        'group_base_dn': 'OU=groups,DC=example,DC=com',
        'group_search_filter': None, 'member_attribute': None,
        'sync_alias': None, 'sync_email': None, 'sync_pager': None,
        'sync_contact_groups': False, 'role_mappings': [],
        'handle_nested_groups': False, 'sync_interval': 5,
        'deactivated': False, 'remove_if_found': False,
    }
    fields.update(kwargs)
    return SimpleNamespace(**fields)


def _role(role, group_dn):
    return SimpleNamespace(role=role, group_dn=group_dn)


class TestBuildPayload(unittest.TestCase):
    """Payload built from the connection and its LDAP Account"""

    def test_server_from_account(self):
        connection = build_payload(_connection(), ACCOUNT)['ldap_connection']
        self.assertEqual(connection['directory_type']['ldap_server'], 'dc1.example.com')
        self.assertEqual(connection['tcp_port'], {'state': 'enabled', 'port': 636})
        self.assertEqual(connection['ssl_encryption'], 'enable_ssl')
        self.assertEqual(connection['bind_credentials']['explicit_password'], 'secret')

    def test_plain_ldap_with_port(self):
        account = dict(ACCOUNT, address='ldap://dc1.example.com:3268')
        connection = build_payload(_connection(), account)['ldap_connection']
        self.assertEqual(connection['tcp_port']['port'], 3268)
        self.assertEqual(connection['ssl_encryption'], 'disable_ssl')

    def test_no_username_binds_anonymous(self):
        account = dict(ACCOUNT, username='')
        connection = build_payload(_connection(), account)['ldap_connection']
        self.assertEqual(connection['bind_credentials'], {'state': 'disabled'})

    @patch.object(ldap_connections, 'password_ident', return_value='cmdbsyncer_42')
    def test_bind_secret_uses_password_store(self, _ident):
        payload = build_payload(_connection(bind_secret='ad-bind'), ACCOUNT)
        bind = payload['ldap_connection']['bind_credentials']
        self.assertEqual(bind['type'], 'store')
        self.assertEqual(bind['password_store_id'], 'cmdbsyncer_42')
        self.assertNotIn('explicit_password', bind)

    def test_roles_grouped_per_role(self):
        mappings = [
            _role('admin', 'CN=a,OU=groups,DC=example,DC=com'),
            _role('admin', 'CN=b,OU=groups,DC=example,DC=com'),
        ]
        roles = build_payload(_connection(role_mappings=mappings),
                              ACCOUNT)['sync_plugins']['groups_to_roles']
        self.assertEqual(roles['state'], 'enabled')
        self.assertEqual(len(roles['admin']), 2)
        self.assertNotIn('handle_nested', roles)

    def test_sync_interval_split(self):
        payload = build_payload(_connection(sync_interval=1530), ACCOUNT)
        self.assertEqual(payload['other']['sync_interval'],
                         {'days': 1, 'hours': 1, 'minutes': 30})


class TestNeedsUpdate(unittest.TestCase):
    """Only managed settings count as a change"""

    def setUp(self):
        mappings = [_role('admin', 'CN=a,DC=example,DC=com')]
        self.payload = build_payload(_connection(role_mappings=mappings), ACCOUNT)
        self.current = copy.deepcopy(self.payload)
        self.current['sync_plugins']['ui_theme'] = {'state': 'disabled'}

    def test_unmanaged_settings_ignored(self):
        self.assertFalse(needs_update(self.payload, self.current))

    def test_changed_value(self):
        self.current['users']['user_base_dn'] = 'OU=other,DC=example,DC=com'
        self.assertTrue(needs_update(self.payload, self.current))

    def test_removed_role_is_a_change(self):
        self.current['sync_plugins']['groups_to_roles']['user'] = [
            {'group_dn': 'CN=u,DC=example,DC=com', 'search_in': 'this_connection'}]
        self.assertTrue(needs_update(self.payload, self.current))


class TestExport(unittest.TestCase):
    """Create, update and delete against the Checkmk API"""

    def setUp(self):
        patcher = patch('application.plugins.checkmk.ldap_connections.CMK2.__init__',
                        lambda self_param, account=False: base_mock_init(self_param))
        patcher.start()
        self.addCleanup(patcher.stop)
        account_patcher = patch.object(ldap_connections, 'get_account_by_name',
                                       return_value=dict(ACCOUNT))
        account_patcher.start()
        self.addCleanup(account_patcher.stop)
        self.sync = CheckmkLdapConnectionSync()

    @patch('builtins.print')
    def test_create_when_missing(self, _print):
        with patch.object(self.sync, 'request', return_value=({}, {})) as request:
            self.sync.export_connection(_connection())
        self.assertEqual(request.call_args.kwargs['method'], 'POST')

    @patch('builtins.print')
    def test_nothing_to_do(self, _print):
        current = {'extensions': build_payload(_connection(), ACCOUNT)}
        with patch.object(self.sync, 'request',
                          return_value=(current, {'ETag': '"x"'})) as request:
            self.sync.export_connection(_connection())
        self.assertEqual(request.call_count, 1)

    @patch('builtins.print')
    def test_update_sends_etag(self, _print):
        current = {'extensions': build_payload(_connection(), ACCOUNT)}
        with patch.object(self.sync, 'request',
                          return_value=(current, {'ETag': '"x"'})) as request:
            self.sync.export_connection(_connection(description='changed'))
        self.assertEqual(request.call_args.kwargs['method'], 'PUT')
        self.assertEqual(request.call_args.kwargs['additional_header'], {'if-match': '"x"'})

    @patch('builtins.print')
    def test_remove_if_found(self, _print):
        with patch.object(self.sync, 'request',
                          return_value=({'extensions': {}}, {'ETag': '"x"'})) as request:
            self.sync.export_connection(_connection(remove_if_found=True))
        self.assertEqual(request.call_args.kwargs['method'], 'DELETE')


if __name__ == '__main__':
    unittest.main()
