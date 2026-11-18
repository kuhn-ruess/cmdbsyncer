"""
Connection and paged search of the LDAP import, against a fake ldap3 connection
"""
# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods
import io
import ssl
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from ldap3.core.exceptions import LDAPSocketOpenError, LDAPStartTLSError

from application.plugins.ldap import ldap as ldap_module
from application.plugins.ldap.ldap import PAGED_RESULTS_OID


CONFIG = {
    'name': 'ldap-test',
    'address': 'ldaps://ldap.example.com',
    'username': 'cn=reader,dc=example,dc=com',
    'password': 'secret',
    'base_dn': 'dc=example,dc=com',
    'search_filter': '(objectClass=computer)',
    'attributes': '',
    'debug': False,
}


def _entry(dn, **attributes):
    return {'type': 'searchResEntry', 'dn': dn, 'raw_attributes': attributes}


class FakeConnection:
    """Answers each search with the next page"""

    def __init__(self, pages, paged=True):
        self.pages = list(pages)
        self.paged = paged
        self.searches = []
        self.response = []
        self.result = {}

    def search(self, base, search_filter, scope, **kwargs):
        self.searches.append((base, search_filter, scope, kwargs))
        cookie, self.response = self.pages.pop(0)
        controls = {}
        if self.paged:
            controls[PAGED_RESULTS_OID] = {'value': {'cookie': cookie}}
        self.result = {'controls': controls}


class SearchTest(unittest.TestCase):

    def test_all_pages_are_read(self):
        connect = FakeConnection([
            (b'next', [_entry('cn=srv01,dc=example,dc=com', cn=[b'srv01'])]),
            (b'', [_entry('cn=srv02,dc=example,dc=com', cn=[b'srv02'])]),
        ])
        results = list(ldap_module._search(connect, CONFIG))  # pylint: disable=protected-access
        self.assertEqual(results, [
            ('cn=srv01,dc=example,dc=com', {'cn': [b'srv01']}),
            ('cn=srv02,dc=example,dc=com', {'cn': [b'srv02']}),
        ])
        self.assertIsNone(connect.searches[0][3]['paged_cookie'])
        self.assertEqual(connect.searches[1][3]['paged_cookie'], b'next')

    def test_empty_attributes_ask_for_all(self):
        connect = FakeConnection([(b'', [])])
        list(ldap_module._search(connect, CONFIG))  # pylint: disable=protected-access
        self.assertEqual(connect.searches[0][3]['attributes'], '*')

    def test_given_attributes_are_asked_for(self):
        connect = FakeConnection([(b'', [])])
        config = dict(CONFIG, attributes='cn, memberOf')
        list(ldap_module._search(connect, config))  # pylint: disable=protected-access
        self.assertEqual(connect.searches[0][3]['attributes'], ['cn', 'memberOf'])

    def test_a_referral_is_no_object(self):
        connect = FakeConnection([
            (b'', [{'type': 'searchResRef', 'uri': ['ldap://other.example.com/']}]),
        ])
        results = list(ldap_module._search(connect, CONFIG))  # pylint: disable=protected-access
        self.assertEqual(results, [(None, ['ldap://other.example.com/'])])

    def test_the_limit_stops_the_search(self):
        connect = FakeConnection([
            (b'next', [_entry('cn=a', cn=[b'a']), _entry('cn=b', cn=[b'b'])]),
            (b'', [_entry('cn=c', cn=[b'c'])]),
        ])
        results = list(ldap_module._search(connect, CONFIG, limit=1))  # pylint: disable=protected-access
        self.assertEqual(len(results), 1)
        self.assertEqual(len(connect.searches), 1)

    def test_a_server_without_paging_is_refused(self):
        connect = FakeConnection([(b'', [])], paged=False)
        with self.assertRaisesRegex(ValueError, 'RFC 2696'):
            list(ldap_module._search(connect, CONFIG))  # pylint: disable=protected-access


class ConnectTest(unittest.TestCase):

    def _connect(self, config, connections):
        with mock.patch.object(ldap_module, '_open', side_effect=connections) as opened, \
                mock.patch.object(ldap_module, 'log'), \
                redirect_stdout(io.StringIO()):
            return ldap_module._connect(config), opened  # pylint: disable=protected-access

    def test_ldaps_binds_without_starttls(self):
        connection = mock.Mock()
        result, _opened = self._connect(CONFIG, [connection])
        self.assertIs(result, connection)
        connection.start_tls.assert_not_called()
        connection.bind.assert_called_once()

    def test_plain_ldap_is_upgraded(self):
        connection = mock.Mock()
        result, _opened = self._connect(dict(CONFIG, address='ldap://ldap.example.com'),
                                        [connection])
        self.assertIs(result, connection)
        connection.start_tls.assert_called_once()
        connection.bind.assert_called_once()

    def test_failed_starttls_stops_unless_allowed(self):
        connection = mock.Mock()
        connection.start_tls.side_effect = LDAPStartTLSError('refused')
        result, _opened = self._connect(dict(CONFIG, address='ldap://ldap.example.com'),
                                        [connection])
        self.assertIsNone(result)
        connection.bind.assert_not_called()

    def test_failed_starttls_reconnects_when_allowed(self):
        first, second = mock.Mock(), mock.Mock()
        first.start_tls.side_effect = LDAPStartTLSError('refused')
        config = dict(CONFIG, address='ldap://ldap.example.com', allow_unencrypted='yes')
        result, opened = self._connect(config, [first, second])
        self.assertIs(result, second)
        self.assertEqual(opened.call_count, 2)
        second.bind.assert_called_once()

    def test_unreachable_server_returns_none(self):
        result, _opened = self._connect(CONFIG, LDAPSocketOpenError('unreachable'))
        self.assertIsNone(result)

    def test_the_certificate_is_verified(self):
        with tempfile.NamedTemporaryFile(suffix='.pem') as ca_file, \
                mock.patch.object(ldap_module, 'Connection') as connection:
            ldap_module._open(dict(CONFIG, tls_ca_file=ca_file.name))  # pylint: disable=protected-access
        tls = connection.call_args.args[0].tls
        self.assertEqual(tls.validate, ssl.CERT_REQUIRED)
        self.assertEqual(tls.ca_certs_file, ca_file.name)

    def test_without_ca_file_the_system_cas_are_used(self):
        with mock.patch.object(ldap_module, 'Connection') as connection:
            ldap_module._open(CONFIG)  # pylint: disable=protected-access
        tls = connection.call_args.args[0].tls
        self.assertEqual(tls.validate, ssl.CERT_REQUIRED)
        self.assertIsNone(tls.ca_certs_file)


if __name__ == '__main__':
    unittest.main()
