"""
Unit tests for the ServiceNow Table API request
"""
# pylint: disable=missing-function-docstring
import unittest
from unittest.mock import patch

import application.plugins.servicenow.syncer as snow
from application.plugins.servicenow.syncer import ServiceNowError, SyncServiceNow


def syncer(**config):
    """A syncer with a config but without a connection behind it."""
    instance = SyncServiceNow.__new__(SyncServiceNow)
    instance.config = {'address': 'https://instance.service-now.com'} | config
    return instance


class FakeResponse:
    """The bits of a requests Response the Table API reads."""

    url = 'https://instance.service-now.com/api/now/table/cmdb_ci_server'

    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = text
        self._payload = payload

    def json(self):
        """A body that is no JSON raises, the same way requests does."""
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def __repr__(self):
        return f"<FakeResponse {self.status_code}>"


class TestTableUrl(unittest.TestCase):
    """Tests for SyncServiceNow.table_url"""

    def test_account_without_the_field_asks_a_plain_instance(self):
        # Accounts created before the field existed have no api_path
        self.assertEqual(
            syncer().table_url('cmdb_ci_server'),
            'https://instance.service-now.com/api/now/table/cmdb_ci_server')

    def test_trailing_slash_of_the_address_is_dropped(self):
        self.assertEqual(
            syncer(address='https://instance.service-now.com/').table_url('cmdb_ci_server'),
            'https://instance.service-now.com/api/now/table/cmdb_ci_server')

    def test_gateway_context_path_is_used(self):
        self.assertEqual(
            syncer(address='https://gateway.example.com',
                   api_path='/servicenow/v1').table_url('cmdb_ci_unix_server'),
            'https://gateway.example.com/servicenow/v1/table/cmdb_ci_unix_server')

    def test_empty_path_puts_the_table_behind_the_address(self):
        # get_account turns an empty custom field into False
        self.assertEqual(
            syncer(address='https://gateway.example.com',
                   api_path=False).table_url('cmdb_ci_unix_server'),
            'https://gateway.example.com/table/cmdb_ci_unix_server')


class TestRecordHostname(unittest.TestCase):
    """Tests for SyncServiceNow.record_hostname"""

    def test_default_field_is_name(self):
        self.assertEqual(syncer().record_hostname({'name': 'srv01'}), 'srv01')

    def test_empty_hostname_field_falls_back_to_name(self):
        # get_account turns an empty custom field into False
        self.assertEqual(syncer(hostname_field=False).record_hostname({'name': 'srv01'}), 'srv01')

    def test_record_without_the_field_has_no_hostname(self):
        self.assertEqual(syncer(hostname_field='fqdn').record_hostname({'name': 'srv01'}), '')

    def test_rewrite_is_applied(self):
        labels = {'name': 'srv01'}
        with patch.object(snow.Host, 'rewrite_hostname', create=True,
                          return_value='srv01.example.com') as rewrite:
            self.assertEqual(
                syncer(rewrite_hostname='{{name}}.example.com').record_hostname(labels),
                'srv01.example.com')
        rewrite.assert_called_once_with('srv01', '{{name}}.example.com', labels)


class TestReadPage(unittest.TestCase):
    """Tests for SyncServiceNow.read_page"""

    def _read(self, response):
        instance = syncer(username='u', password='p')
        instance.inner_request = lambda *args, **kwargs: response
        return instance.read_page('cmdb_ci_server', {})

    def test_records_are_returned(self):
        self.assertEqual(self._read(FakeResponse(payload={'result': [{'name': 'srv01'}]})),
                         [{'name': 'srv01'}])

    def test_answer_without_json_names_the_url_and_the_answer(self):
        # A gateway with another context path answers with plain text
        with self.assertRaises(ServiceNowError) as caught:
            self._read(FakeResponse(status_code=404,
                                    text='No context-path matches the request URI'))
        self.assertIn('404', str(caught.exception))
        self.assertIn('/api/now/table/cmdb_ci_server', str(caught.exception))
        self.assertIn('No context-path matches', str(caught.exception))

    def test_invalid_login_is_named(self):
        with self.assertRaises(ServiceNowError) as caught:
            self._read(FakeResponse(status_code=401, text='Required to provide Auth information'))
        self.assertIn('Invalid login', str(caught.exception))

    def test_error_of_the_instance_is_shown(self):
        with self.assertRaises(ServiceNowError) as caught:
            self._read(FakeResponse(status_code=400, payload={
                'error': {'message': 'Invalid table name', 'detail': 'no such table'}}))
        self.assertIn('Invalid table name', str(caught.exception))
        self.assertIn('no such table', str(caught.exception))


class TestImportHosts(unittest.TestCase):
    """Tests for SyncServiceNow.import_hosts"""

    def test_account_without_a_table_says_so(self):
        # An empty custom field arrives as False and used to raise an
        # AttributeError deep inside the import instead
        instance = syncer(tables=False)
        instance.log_details = []
        with self.assertRaises(ServiceNowError) as caught:
            instance.import_hosts()
        self.assertIn("no table", str(caught.exception))

    def test_every_table_of_the_account_is_read(self):
        instance = syncer(tables='cmdb_ci_unix_server, cmdb_ci_db_instance')
        instance.log_details = []
        read = []
        instance.get_table = lambda table: read.append(table) or []
        instance.import_hosts()
        self.assertEqual(read, ['cmdb_ci_unix_server', 'cmdb_ci_db_instance'])
