"""
Unit tests for the ServiceNow Table API request
"""
# pylint: disable=missing-function-docstring
import unittest
from unittest.mock import patch

import application.plugins.servicenow.syncer as snow
from application.plugins.servicenow.syncer import (ServiceNowError, SyncServiceNow,
                                                  parse_inventorize_tables)


class _FakeProgress:  # pylint: disable=unused-argument
    """Stand-in for the read spinner — rich's console is stubbed in tests."""

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def add_task(self, *args, **kwargs):
        """The spinner has exactly one task"""
        return 1

    def update(self, *args, **kwargs):
        """Nothing to draw"""


def setUpModule():  # pylint: disable=invalid-name
    """Read every table without a spinner"""
    patcher = patch.object(snow, 'read_progress', _FakeProgress())
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def syncer(hosts=None, **config):
    """A syncer with a config but without a connection behind it."""
    instance = SyncServiceNow.__new__(SyncServiceNow)
    instance.config = {'address': 'https://instance.service-now.com'} | config
    # The host lookup would go to the database otherwise
    instance._host_index = hosts if hosts is not None else {}  # pylint: disable=protected-access
    instance._host_sys_ids = set()  # pylint: disable=protected-access
    # So would the check which of the named CIs are hosts; the tests
    # that care about it call the real one
    instance.drop_unknown_hosts = lambda grouped, table: grouped
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
        instance.get_table = lambda table, query=None, fields=None: read.append(table) or []
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
        instance.get_table = lambda table, query=None, fields=None: iter(
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
        instance.get_table = lambda table, query=None, fields=None: iter(self.RELATIONS)
        index = instance.relation_index()
        self.assertEqual(index['ldom-s02-ora'], {'ldom-s02'})
        self.assertEqual(index['ldom-s02'], {'LDOM-S02-ORA'})

    def test_a_half_empty_relation_is_ignored(self):
        instance = syncer()
        instance.get_table = lambda table, query=None, fields=None: iter(self.RELATIONS)
        self.assertEqual(len(instance.relation_index()), 4)

    def test_the_table_is_read_once_per_inventorized_table(self):
        instance = syncer()
        reads = []
        instance.get_table = lambda table, query=None, fields=None: \
            reads.append(table) or iter(self.RELATIONS)
        instance.relation_index('cmdb_ci_db_instance')
        instance.relation_index('cmdb_ci_db_instance')
        self.assertEqual(reads, ['cmdb_rel_ci'])

    def test_the_class_of_the_table_narrows_the_read(self):
        # Only a relation with that class on one of its ends can ever be
        # looked up, so the rest must not be read at all
        self.assertEqual(
            syncer().relation_query('cmdb_ci_db_instance'),
            'child.sys_class_nameINSTANCEOFcmdb_ci_db_instance'
            '^ORparent.sys_class_nameINSTANCEOFcmdb_ci_db_instance')

    def test_the_types_and_the_class_narrow_it_together(self):
        instance = syncer(inventorize_relation_types='Contains::Contained by')
        self.assertEqual(
            instance.relation_query('cmdb_ci_cluster'),
            'type.nameINContains::Contained by'
            '^child.sys_class_nameINSTANCEOFcmdb_ci_cluster'
            '^ORparent.sys_class_nameINSTANCEOFcmdb_ci_cluster')

    def test_an_empty_answer_falls_back_to_the_whole_table(self):
        # An instance that does not answer the narrowed query the way it
        # is meant to would leave every record without a host
        instance = syncer()
        queries = []

        def read(table, query=None, fields=None):  # pylint: disable=unused-argument
            queries.append(query)
            return iter(self.RELATIONS if len(queries) > 1 else [])

        instance.get_table = read
        index = instance.relation_index('cmdb_ci_db_instance')
        self.assertEqual(queries, ['child.sys_class_nameINSTANCEOFcmdb_ci_db_instance'
                                   '^ORparent.sys_class_nameINSTANCEOFcmdb_ci_db_instance', ''])
        self.assertEqual(index['ldom-s02'], {'LDOM-S02-ORA'})

    def test_the_fallback_read_is_shared_by_every_table(self):
        # The unnarrowed read is the expensive one, so two tables both
        # falling back to it must not page through the whole table twice
        instance = syncer()
        queries = []

        def read(table, query=None, fields=None):  # pylint: disable=unused-argument
            queries.append(query)
            return iter([] if query else self.RELATIONS)

        instance.get_table = read
        instance.relation_index('cmdb_ci_db_instance')
        instance.relation_index('cmdb_ci_appl')
        self.assertEqual(queries.count(''), 1)

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
        instance.get_table = lambda table, query=None, fields=None: iter(self.ADAPTERS)
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

    def test_the_relations_are_read_before_the_table(self):
        # Both reads run under a spinner, and rich allows only one live
        # display at a time — so the lazy read may not happen inside the
        # spinner of the table
        instance = syncer(inventorize_key='snow',
                          inventorize_tables='cmdb_ci_db_instance:rel')
        instance.log_details = []
        reads = []
        instance.get_table = lambda table, query=None, fields=None: \
            reads.append(table) or iter([])
        with patch.object(snow, 'run_inventory'):
            instance.inventorize_data()
        self.assertEqual(reads[-1], 'cmdb_ci_db_instance')
        self.assertNotIn('cmdb_ci_db_instance', reads[:-1])

    def test_a_table_can_be_matched_through_the_relationship_table(self):
        instance = syncer(inventorize_key='snow',
                          inventorize_tables='cmdb_ci_db_instance:rel')
        instance.log_details = []
        tables = {
            'cmdb_rel_ci': [{'parent': 'LDOM-S02-ORA', 'child': 'ldom-s02',
                             'type': 'Contains::Contained by'}],
            'cmdb_ci_db_instance': [{'name': 'LDOM-S02-ORA', 'version': '19c'}],
        }
        instance.get_table = lambda table, query=None, fields=None: iter(tables[table])
        with patch.object(snow, 'run_inventory') as run:
            instance.inventorize_data()
        _config, objects = run.call_args[0]
        self.assertEqual(dict(objects),
                         {'ldom-s02': {'0_name': 'LDOM-S02-ORA', '0_version': '19c'}})

    def test_records_without_a_ci_are_counted_not_logged_one_by_one(self):
        # One log entry per skipped record let the log of a run against
        # a large instance grow without an end
        instance = syncer(inventorize_key='snow',
                          inventorize_tables='cmdb_ci_network_adapter:cmdb_ci')
        instance.log_details = []
        instance.get_table = lambda table, query=None, fields=None: iter(self.ADAPTERS)
        with patch.object(snow, 'run_inventory'):
            instance.inventorize_data()
        self.assertIn(('cmdb_ci_network_adapter_records_without_ci', 1),
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


class TestInventorizeQuery(unittest.TestCase):
    """The query an inventorized table is read with"""

    @staticmethod
    def _syncer(sys_ids=(), **config):
        instance = syncer(**config)
        instance._host_sys_ids = set(sys_ids)  # pylint: disable=protected-access
        return instance

    def test_the_read_is_narrowed_to_the_hosts_of_the_account(self):
        # The sys_id is what the reference really holds, so this asks
        # the exact question instead of guessing at the class hierarchy
        instance = self._syncer(sys_ids=['aaa', 'bbb'])
        self.assertEqual(instance.inventorize_queries('cmdb_ci'),
                         (['cmdb_ciINaaa,bbb'], True))

    def test_the_sys_ids_go_out_in_chunks(self):
        ids = [f'{x:032x}' for x in range(snow.SYS_ID_CHUNK + 1)]
        queries, derived = self._syncer(sys_ids=ids).inventorize_queries('cmdb_ci')
        self.assertTrue(derived)
        self.assertEqual(len(queries), 2)
        self.assertEqual(sorted(','.join(x.split('IN', 1)[1] for x in queries).split(',')),
                         sorted(ids))

    def test_the_account_query_wins_and_is_not_a_guess(self):
        instance = self._syncer(sys_ids=['aaa'], inventorize_query='install_status=1')
        self.assertEqual(instance.inventorize_queries('cmdb_ci'), (['install_status=1'], False))

    def test_a_relation_is_narrowed_on_the_relationship_table(self):
        self.assertEqual(self._syncer(sys_ids=['aaa']).inventorize_queries('rel'),
                         ([''], False))

    def test_hosts_imported_without_a_sys_id_cannot_be_asked_for(self):
        self.assertEqual(self._syncer().inventorize_queries('cmdb_ci'), ([''], False))

    def test_the_import_query_and_fields_stay_out_of_the_read(self):
        # They belong to the table imported as hosts; a field list of it
        # would drop the very field the matcher needs
        instance = self._syncer(sys_ids=['aaa'], inventorize_key='snow',
                                sysparm_query='operational_status=1',
                                sysparm_fields='name,sys_id',
                                inventorize_tables='cmdb_ci_network_adapter:cmdb_ci')
        instance.log_details = []
        calls = []

        def read(table, query=None, fields=None):  # pylint: disable=unused-argument
            calls.append((query, fields))
            return iter([{'name': 'eth0', 'cmdb_ci': 'srv01'}])

        instance.get_table = read
        with patch.object(snow, 'run_inventory'):
            instance.inventorize_data()
        self.assertEqual(calls, [('cmdb_ciINaaa', '')])

    def test_a_derived_query_that_finds_nothing_gives_way(self):
        instance = self._syncer(sys_ids=['aaa'], inventorize_key='snow',
                                inventorize_tables='cmdb_ci_network_adapter:cmdb_ci')
        instance.log_details = []
        queries = []

        def read(table, query=None, fields=None):  # pylint: disable=unused-argument
            queries.append(query)
            return iter([] if len(queries) == 1 else [{'name': 'eth0', 'cmdb_ci': 'srv01'}])

        instance.get_table = read
        with patch.object(snow, 'run_inventory') as run:
            instance.inventorize_data()
        self.assertEqual(queries, ['cmdb_ciINaaa', ''])
        self.assertEqual(dict(run.call_args[0][1]),
                         {'srv01': {'0_name': 'eth0', '0_cmdb_ci': 'srv01'}})


class TestDropUnknownHosts(unittest.TestCase):
    """A named CI the Syncer has no host for is dropped before the write"""

    @staticmethod
    def _drop(instance, grouped, known):
        """The real method, with the database answering `known`"""
        instance.log_details = []
        with patch.object(snow.Host, 'objects', create=True) as objects:
            objects.return_value.distinct.return_value = known
            return SyncServiceNow.drop_unknown_hosts(instance, grouped,
                                                     'cmdb_ci_network_adapter')

    def test_only_the_hosts_the_syncer_has_are_kept(self):
        self.assertEqual(
            self._drop(syncer(), {'srv01': [{}], 'iphone-se': [{}]}, ['srv01']),
            {'srv01': [{}]})

    def test_a_lowercased_host_still_counts_as_known(self):
        self.assertEqual(self._drop(syncer(), {'SRV01': [{}]}, ['srv01']), {'SRV01': [{}]})

    def test_the_dropped_ones_are_counted(self):
        instance = syncer()
        self._drop(instance, {'srv01': [], 'iphone-se': []}, ['srv01'])
        self.assertIn(('cmdb_ci_network_adapter_ci_without_host', 1), instance.log_details)

    def test_a_domain_match_cannot_be_looked_up_exactly(self):
        grouped = {'srv01': [{}]}
        instance = syncer(inventorize_match_by_domain=True)
        with patch.object(snow.Host, 'objects', create=True) as objects:
            self.assertEqual(
                SyncServiceNow.drop_unknown_hosts(instance, grouped, 'a_table'), grouped)
            objects.assert_not_called()


class TestHostLookup(unittest.TestCase):
    """The referenced CI name is resolved to the host it became"""

    def test_the_label_lookup_finds_the_renamed_host(self):
        # The relation names the CI, the import created the host with
        # the domain appended
        instance = syncer(hosts={'ldom-s02': 'ldom-s02.munich-airport.de'})
        instance.get_table = lambda table, query=None, fields=None: iter(
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
