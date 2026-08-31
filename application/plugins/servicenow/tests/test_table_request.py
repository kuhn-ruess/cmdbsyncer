"""
Unit tests for the ServiceNow Table API request
"""
# pylint: disable=missing-function-docstring
import unittest
from unittest.mock import patch

import application.plugins.servicenow.syncer as snow
from application.plugins.servicenow.syncer import (ServiceNowError, SyncServiceNow,
                                                  parse_inventorize_tables)


def syncer(hosts=None, **config):
    """A syncer with a config but without a connection behind it."""
    instance = SyncServiceNow.__new__(SyncServiceNow)
    instance.config = {'address': 'https://instance.service-now.com'} | config
    # The host lookup would go to the database otherwise
    instance._host_index = hosts if hosts is not None else {}  # pylint: disable=protected-access
    return instance


class FakeResponse:
    """The bits of a requests Response the Table API reads."""

    url = 'https://instance.service-now.com/api/now/table/cmdb_ci_server'

    def __init__(self, status_code=200, payload=None, text='', headers=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = text
        self.headers = headers or {}
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


class TestFlattenRecord(unittest.TestCase):
    """Tests for SyncServiceNow.flatten_record"""

    RECORD = {'name': 'srv01', 'fqdn': '', 'os': None,
              'assigned_to': {'display_value': 'Jane', 'value': 'abc'}}

    def test_the_import_drops_the_empty_fields(self):
        self.assertEqual(SyncServiceNow.flatten_record(self.RECORD),
                         {'name': 'srv01', 'assigned_to': 'Jane'})

    def test_a_query_keeps_them_so_the_field_is_visible(self):
        # Hiding them made a record look like it has no fqdn field at
        # all, instead of an empty one
        self.assertEqual(SyncServiceNow.flatten_record(self.RECORD, keep_empty=True),
                         {'name': 'srv01', 'fqdn': '', 'os': '',
                          'assigned_to': 'Jane'})


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

    def test_the_remaining_quota_is_kept_for_the_query_view(self):
        instance = syncer(username='u', password='p')
        response = FakeResponse(payload={'result': []},
                                headers={'X-RateLimit-Remaining': '4711'})
        instance.inner_request = lambda *args, **kwargs: response
        instance.read_page('cmdb_ci_server', {})
        self.assertEqual(instance.last_rate_limit, {'X-RateLimit-Remaining': '4711'})

    def test_answer_without_json_names_the_url_and_the_answer(self):
        # A gateway with another context path answers with plain text
        with self.assertRaises(ServiceNowError) as caught:
            self._read(FakeResponse(status_code=404,
                                    text='No context-path matches the request URI'))
        self.assertIn('404', str(caught.exception))
        self.assertIn('/api/now/table/cmdb_ci_server', str(caught.exception))
        self.assertIn('No context-path matches', str(caught.exception))

    def test_invalid_login_is_named_and_keeps_the_answer(self):
        # The body is what tells a wrong password from a locked user
        with self.assertRaises(ServiceNowError) as caught:
            self._read(FakeResponse(status_code=401, text='User Not Authenticated'))
        self.assertIn('invalid login', str(caught.exception))
        self.assertIn('User Not Authenticated', str(caught.exception))

    def test_rate_limit_is_not_reported_as_invalid_login(self):
        with self.assertRaises(ServiceNowError) as caught:
            self._read(FakeResponse(status_code=429, text='Maximum request limit exceeded',
                                    headers={'X-RateLimit-Remaining': '0',
                                             'Retry-After': '60'}))
        message = str(caught.exception)
        self.assertIn('rate limiting', message)
        self.assertNotIn('invalid login', message)
        self.assertIn('Retry-After: 60', message)

    def test_a_throttling_gateway_answering_401_shows_its_headers(self):
        # Some gateways throttle with a 401 instead of a 429 — then the
        # headers are the only thing that says what really happened
        with self.assertRaises(ServiceNowError) as caught:
            self._read(FakeResponse(status_code=401, text='rate limit exceeded',
                                    headers={'X-RateLimit-Remaining': '0'}))
        self.assertIn('X-RateLimit-Remaining: 0', str(caught.exception))

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
        instance.get_table = lambda table, query=None: read.append(table) or []
        instance.import_hosts()
        self.assertEqual(read, ['cmdb_ci_unix_server', 'cmdb_ci_db_instance'])


class TestInventorizeTables(unittest.TestCase):
    """Tests for parse_inventorize_tables"""

    def test_pairs_are_read(self):
        self.assertEqual(
            parse_inventorize_tables(
                'cmdb_ci_network_adapter:cmdb_ci, cmdb_ci_db_instance:used_for'),
            [('cmdb_ci_network_adapter', 'cmdb_ci'),
             ('cmdb_ci_db_instance', 'used_for')])

    def test_nothing_configured(self):
        self.assertEqual(parse_inventorize_tables(''), [])
        # An empty custom field arrives as False
        self.assertEqual(parse_inventorize_tables(False), [])

    def test_a_typo_is_not_swallowed(self):
        # Skipping it would drop a whole table without a word
        with self.assertRaises(ServiceNowError) as caught:
            parse_inventorize_tables('cmdb_ci_network_adapter')
        self.assertIn('table:field', str(caught.exception))


class TestRecordHosts(unittest.TestCase):
    """Tests for SyncServiceNow.record_hosts"""

    def test_the_reference_field_names_the_host(self):
        self.assertEqual(
            syncer().record_hosts({'name': 'eth0', 'cmdb_ci': 'srv01'}, 'cmdb_ci'),
            ['srv01'])

    def test_a_record_without_the_reference_has_no_host(self):
        self.assertEqual(syncer().record_hosts({'name': 'eth0'}, 'cmdb_ci'), [])

    def test_the_rewrite_is_applied(self):
        labels = {'name': 'eth0', 'cmdb_ci': 'srv01'}
        with patch.object(snow.Host, 'rewrite_hostname', create=True,
                          return_value='srv01.example.com') as rewrite:
            self.assertEqual(
                syncer(inventorize_rewrite_parent='{{HOSTNAME}}.example.com')
                .record_hosts(labels, 'cmdb_ci'),
                ['srv01.example.com'])
        rewrite.assert_called_once_with('srv01', '{{HOSTNAME}}.example.com', labels)

    @staticmethod
    def _with_relations(*relations):
        instance = syncer()
        instance.get_table = lambda table, query=None: iter(
            [{'parent': parent, 'child': child, 'type': 'Contains::Contained by'}
             for parent, child in relations])
        return instance

    def test_the_relationship_table_finds_the_host(self):
        instance = self._with_relations(('LDOM-S02-ORA', 'ldom-s02'))
        self.assertEqual(instance.record_hosts({'name': 'LDOM-S02-ORA'}, 'rel'),
                         ['ldom-s02'])

    def test_a_record_related_to_two_hosts_lands_on_both(self):
        instance = self._with_relations(('cluster-db', 'srv02'), ('cluster-db', 'srv01'))
        self.assertEqual(instance.record_hosts({'name': 'cluster-db'}, 'rel'),
                         ['srv01', 'srv02'])

    def test_a_record_without_a_relation_has_no_host(self):
        instance = self._with_relations(('LDOM-S02-ORA', 'ldom-s02'))
        self.assertEqual(instance.record_hosts({'name': 'lonely'}, 'rel'), [])


class TestRelationIndex(unittest.TestCase):
    """Tests for the relationship table read"""

    RELATIONS = [
        {'parent': 'LDOM-S02-ORA', 'child': 'ldom-s02', 'type': 'Contains::Contained by'},
        {'parent': 'VISMAN', 'child': 'ldom-s14', 'type': 'Contains::Contained by'},
        {'parent': '', 'child': 'ldom-s14', 'type': 'Contains::Contained by'},
    ]

    def test_both_directions_are_indexed(self):
        # Whether the host is the parent or the child depends on the
        # relation type, so neither side may be the only one indexed
        instance = syncer()
        instance.get_table = lambda table, query=None: iter(self.RELATIONS)
        index = instance.relation_index()
        self.assertEqual(index['ldom-s02-ora'], {'ldom-s02'})
        self.assertEqual(index['ldom-s02'], {'LDOM-S02-ORA'})

    def test_a_half_empty_relation_is_ignored(self):
        instance = syncer()
        instance.get_table = lambda table, query=None: iter(self.RELATIONS)
        self.assertEqual(len(instance.relation_index()), 4)

    def test_the_table_is_read_once(self):
        instance = syncer()
        reads = []
        instance.get_table = lambda table, query=None: reads.append(table) or iter([])
        instance.relation_index()
        instance.relation_index()
        self.assertEqual(reads, ['cmdb_rel_ci'])

    def test_the_types_narrow_the_read_on_the_instance(self):
        instance = syncer(inventorize_relation_types='Contains::Contained by, Owns::Owned by')
        self.assertEqual(instance.relation_query(),
                         'type.nameINContains::Contained by,Owns::Owned by')

    def test_without_types_the_whole_table_is_read(self):
        self.assertEqual(syncer().relation_query(), '')


class TestInventorizeData(unittest.TestCase):
    """Tests for SyncServiceNow.inventorize_data"""

    ADAPTERS = [
        {'name': 'eth0', 'ip_address': '10.0.0.1', 'cmdb_ci': 'srv01'},
        {'name': 'eth1', 'ip_address': '10.0.0.2', 'cmdb_ci': 'srv01'},
        {'name': 'eth0', 'ip_address': '10.0.0.3', 'cmdb_ci': 'srv02'},
        {'name': 'orphan', 'ip_address': '10.0.0.4'},
    ]

    def _run(self, **config):
        instance = syncer(inventorize_key='snow',
                          inventorize_tables='cmdb_ci_network_adapter:cmdb_ci',
                          **config)
        instance.log_details = []
        instance.get_table = lambda table, query=None: iter(self.ADAPTERS)
        with patch.object(snow, 'run_inventory') as run:
            instance.inventorize_data()
        return run

    def test_records_are_grouped_under_their_host(self):
        run = self._run()
        config, objects = run.call_args[0]
        self.assertEqual(run.call_args[1], {'sub_key': 'cmdb_ci_network_adapter'})
        self.assertEqual(config['inventorize_key'], 'snow')
        self.assertEqual(dict(objects), {
            'srv01': {'0_name': 'eth0', '0_ip_address': '10.0.0.1', '0_cmdb_ci': 'srv01',
                      '1_name': 'eth1', '1_ip_address': '10.0.0.2', '1_cmdb_ci': 'srv01'},
            'srv02': {'0_name': 'eth0', '0_ip_address': '10.0.0.3', '0_cmdb_ci': 'srv02'},
        })

    def test_a_table_can_be_matched_through_the_relationship_table(self):
        instance = syncer(inventorize_key='snow',
                          inventorize_tables='cmdb_ci_db_instance:rel')
        instance.log_details = []
        tables = {
            'cmdb_rel_ci': [{'parent': 'LDOM-S02-ORA', 'child': 'ldom-s02',
                             'type': 'Contains::Contained by'}],
            'cmdb_ci_db_instance': [{'name': 'LDOM-S02-ORA', 'version': '19c'}],
        }
        instance.get_table = lambda table, query=None: iter(tables[table])
        with patch.object(snow, 'run_inventory') as run:
            instance.inventorize_data()
        _config, objects = run.call_args[0]
        self.assertEqual(dict(objects),
                         {'ldom-s02': {'0_name': 'LDOM-S02-ORA', '0_version': '19c'}})

    def test_a_record_without_a_host_is_logged_not_imported(self):
        instance = syncer(inventorize_key='snow',
                          inventorize_tables='cmdb_ci_network_adapter:cmdb_ci')
        instance.log_details = []
        instance.get_table = lambda table, query=None: iter(self.ADAPTERS)
        with patch.object(snow, 'run_inventory'):
            instance.inventorize_data()
        self.assertIn(('record_without_host', 'cmdb_ci_network_adapter:cmdb_ci'),
                      instance.log_details)

    def test_the_import_hostname_rewrite_is_not_applied_a_second_time(self):
        # run_inventory would rewrite the parent name with the labels of
        # a child record, which does not carry the server's fields
        config, _objects = self._run(rewrite_hostname='{{fqdn}}').call_args[0]
        self.assertEqual(config['rewrite_hostname'], '')

    def test_an_account_without_a_key_says_so(self):
        instance = syncer(inventorize_tables='cmdb_ci_network_adapter:cmdb_ci')
        instance.log_details = []
        with self.assertRaises(ServiceNowError) as caught:
            instance.inventorize_data()
        self.assertIn('inventorize_key', str(caught.exception))

    def test_an_account_without_a_table_says_so(self):
        instance = syncer(inventorize_key='snow')
        instance.log_details = []
        with self.assertRaises(ServiceNowError) as caught:
            instance.inventorize_data()
        self.assertIn('inventorize_tables', str(caught.exception))


class TestHostLookup(unittest.TestCase):
    """The referenced CI name is resolved to the host it became"""

    def test_the_label_lookup_finds_the_renamed_host(self):
        # The relation names the CI, the import created the host with
        # the domain appended
        instance = syncer(hosts={'ldom-s02': 'ldom-s02.munich-airport.de'})
        instance.get_table = lambda table, query=None: iter(
            [{'parent': 'LDOM-S02-ORA', 'child': 'ldom-s02',
              'type': 'Contains::Contained by'}])
        self.assertEqual(instance.record_hosts({'name': 'LDOM-S02-ORA'}, 'rel'),
                         ['ldom-s02.munich-airport.de'])

    def test_it_works_for_a_reference_field_too(self):
        instance = syncer(hosts={'srv01': 'srv01.example.com'})
        self.assertEqual(
            instance.record_hosts({'name': 'eth0', 'cmdb_ci': 'srv01'}, 'cmdb_ci'),
            ['srv01.example.com'])

    def test_an_unknown_ci_keeps_its_name(self):
        # run_inventory then reports the host as unknown
        self.assertEqual(
            syncer().record_hosts({'name': 'eth0', 'cmdb_ci': 'srv01'}, 'cmdb_ci'),
            ['srv01'])

    def test_the_rewrite_only_applies_to_an_unknown_ci(self):
        instance = syncer(hosts={'srv01': 'srv01.example.com'},
                          inventorize_rewrite_parent='{{HOSTNAME}}.wrong.example.com')
        with patch.object(snow.Host, 'rewrite_hostname', create=True,
                          return_value='srv02.wrong.example.com') as rewrite:
            self.assertEqual(
                instance.record_hosts({'name': 'eth0', 'cmdb_ci': 'srv01'}, 'cmdb_ci'),
                ['srv01.example.com'])
            rewrite.assert_not_called()
            self.assertEqual(
                instance.record_hosts({'name': 'eth1', 'cmdb_ci': 'srv02'}, 'cmdb_ci'),
                ['srv02.wrong.example.com'])
