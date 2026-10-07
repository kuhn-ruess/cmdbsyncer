"""
One imported record may stand for several hosts

Every importer turns a record into its hosts through
application.helpers.import_hostnames: the rewrite_hostname template of
the account runs once, and when it renders a list, every entry becomes a
host of its own with the attributes of the whole record.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods
import csv
import importlib.util
import os
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

from tests import real_render_jinja

import application.helpers.import_hostnames as hostnames
from application.helpers.import_hostnames import (
    get_import_hosts,
    import_hostnames,
    parse_hostname_list,
    update_import_host,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The example from the documentation: one store server record, three
# devices of that store
STORE_TEMPLATE = ("{{ [HOSTNAME, HOSTNAME | replace('HVL01', 'RTR01'), "
                  "HOSTNAME | replace('HVL01', 'SW01')] }}")


def rewrite_hostname(old_name, template, attributes):
    """Host.rewrite_hostname, rendered with real Jinja"""
    return real_render_jinja(template, HOSTNAME=old_name, **attributes)


class FakeHosts:
    """Host.get_host over a dict, every host owned by whoever asks first"""

    def __init__(self, owned_by_other=()):
        self.hosts = {}
        self.owned_by_other = set(owned_by_other)

    def get_host(self, name, create=True):
        if name not in self.hosts:
            if not create:
                return False
            host = Mock(name=name)
            host.hostname = name
            host.set_account.return_value = name not in self.owned_by_other
            self.hosts[name] = host
        return self.hosts[name]


def with_hosts(fake):
    """Patch the Host the helper works with: real rewrite, fake database"""
    host_cls = types.SimpleNamespace(get_host=fake.get_host,
                                     rewrite_hostname=rewrite_hostname)
    return patch.object(hostnames, 'Host', host_cls)


class ParseHostnameListTest(unittest.TestCase):

    def test_a_plain_name_is_no_list(self):
        self.assertIsNone(parse_hostname_list('srv01.example.com'))

    def test_a_comma_alone_splits_nothing(self):
        # A name with a comma keeps the meaning it always had
        self.assertIsNone(parse_hostname_list('srv01,srv02'))
        self.assertIsNone(parse_hostname_list('srv01, srv02'))

    def test_a_python_list_literal(self):
        self.assertEqual(parse_hostname_list("['srv01', 'srv02']"), ['srv01', 'srv02'])

    def test_a_json_list(self):
        self.assertEqual(parse_hostname_list(' ["srv01", "srv02"] '), ['srv01', 'srv02'])

    def test_entries_without_quotes_are_no_list(self):
        self.assertIsNone(parse_hostname_list('[srv01, srv02]'))

    def test_a_tuple_or_dict_is_no_list(self):
        self.assertIsNone(parse_hostname_list("('srv01', 'srv02')"))
        self.assertIsNone(parse_hostname_list("{'srv01': 1}"))

    def test_empty_entries_are_skipped(self):
        self.assertEqual(parse_hostname_list("['srv01', '', '  ', None]"), ['srv01'])

    def test_repeated_entries_are_kept_once_in_order(self):
        self.assertEqual(parse_hostname_list("['b', 'a', 'b', ' a ']"), ['b', 'a'])

    def test_lowercase_hostnames_dedupe_case_insensitive(self):
        with patch.dict(hostnames.app.config, {'LOWERCASE_HOSTNAMES': True}):
            self.assertEqual(parse_hostname_list("['SRV01', 'srv01']"), ['SRV01'])
        with patch.dict(hostnames.app.config, {'LOWERCASE_HOSTNAMES': False}):
            self.assertEqual(parse_hostname_list("['SRV01', 'srv01']"), ['SRV01', 'srv01'])

    def test_numbers_count_nested_values_do_not(self):
        self.assertEqual(parse_hostname_list("[4711, ['x'], {'y': 1}, True]"), ['4711'])

    def test_an_empty_list_names_no_host(self):
        self.assertEqual(parse_hostname_list('[]'), [])


class ImportHostnamesTest(unittest.TestCase):

    def setUp(self):
        patcher = with_hosts(FakeHosts())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_without_a_template_the_name_stays_as_it_is(self):
        self.assertEqual(import_hostnames('srv01', {}, {}), ['srv01'])
        self.assertEqual(import_hostnames('srv01', {'rewrite_hostname': ''}, {}), ['srv01'])
        self.assertEqual(import_hostnames('srv01', {'rewrite_hostname': False}, {}), ['srv01'])

    def test_a_list_from_the_source_is_not_split_without_a_template(self):
        # Splitting is a feature of the rewrite only
        self.assertEqual(import_hostnames("['a', 'b']", {}, {}), ["['a', 'b']"])

    def test_a_template_rendering_a_name_gives_that_name(self):
        config = {'rewrite_hostname': '{{ HOSTNAME }}.{{ domain }}'}
        self.assertEqual(import_hostnames('srv01', config, {'domain': 'example.com'}),
                         ['srv01.example.com'])

    def test_a_template_rendering_commas_still_gives_one_name(self):
        config = {'rewrite_hostname': '{{ HOSTNAME }},{{ site }}'}
        self.assertEqual(import_hostnames('srv01', config, {'site': 'b'}), ['srv01,b'])

    def test_a_template_rendering_nothing_gives_an_empty_name(self):
        # Exactly what the importers got before, they skip it themselves
        config = {'rewrite_hostname': '{% if false %}x{% endif %}'}
        self.assertEqual(import_hostnames('srv01', config, {}), [''])

    def test_a_template_rendering_a_list_names_every_device(self):
        config = {'rewrite_hostname': STORE_TEMPLATE}
        self.assertEqual(import_hostnames('S0815-HVL01', config, {}),
                         ['S0815-HVL01', 'S0815-RTR01', 'S0815-SW01'])

    def test_a_list_built_in_a_loop(self):
        config = {'rewrite_hostname':
                  "[{% for x in devices.split(' ') %}'{{ HOSTNAME }}-{{ x }}',{% endfor %}]"}
        self.assertEqual(import_hostnames('s1', config, {'devices': 'rtr sw rtr'}),
                         ['s1-rtr', 's1-sw'])

    def test_the_record_is_the_context_of_the_template(self):
        config = {'rewrite_hostname': '{{ [HOSTNAME, router] }}'}
        self.assertEqual(import_hostnames('s1', config, {'router': 's1-rtr'}),
                         ['s1', 's1-rtr'])


class GetImportHostsTest(unittest.TestCase):

    def test_one_host_per_name(self):
        fake = FakeHosts()
        with with_hosts(fake):
            found = get_import_hosts('S1-HVL01', {'rewrite_hostname': STORE_TEMPLATE}, {})
        self.assertEqual([name for name, _host in found],
                         ['S1-HVL01', 'S1-RTR01', 'S1-SW01'])
        self.assertEqual([host for _name, host in found],
                         [fake.hosts[x] for x in ['S1-HVL01', 'S1-RTR01', 'S1-SW01']])

    def test_a_plain_name_is_exactly_one_host(self):
        fake = FakeHosts()
        with with_hosts(fake):
            found = get_import_hosts('srv01', {}, {})
        self.assertEqual(found, [('srv01', fake.hosts['srv01'])])

    def test_create_is_handed_on(self):
        fake = FakeHosts()
        with with_hosts(fake):
            self.assertEqual(get_import_hosts('srv01', {}, {}, create=False),
                             [('srv01', False)])


class UpdateImportHostTest(unittest.TestCase):

    def test_labels_account_and_save(self):
        host = Mock()
        host.set_account.return_value = True
        self.assertTrue(update_import_host(host, {'a': 1}, {'name': 'acc'}, import_id='x'))
        host.update_host.assert_called_once_with({'a': 1})
        host.set_account.assert_called_once_with(account_dict={'name': 'acc'}, import_id='x')
        host.save.assert_called_once_with()

    def test_a_host_of_another_master_is_not_saved(self):
        host = Mock()
        host.set_account.return_value = False
        self.assertFalse(update_import_host(host, {}, {}))
        host.save.assert_not_called()


def load_plugin_module(name, relative_path):
    """A plugin module loaded for real, under a name of its own"""
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(REPO_ROOT, 'application', relative_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImporterIntegrationTest(unittest.TestCase):
    """The importers themselves, fed one record that names three devices"""

    CONFIG = {'id': 'acc1', 'name': 'stores', 'rewrite_hostname': STORE_TEMPLATE}

    def assert_three_devices(self, fake, labels):
        self.assertEqual(sorted(fake.hosts), ['S1-HVL01', 'S1-RTR01', 'S1-SW01'])
        for host in fake.hosts.values():
            host.update_host.assert_called_once_with(labels)
            self.assertEqual(host.set_account.call_args.kwargs['account_dict']['name'],
                             'stores')
            host.save.assert_called_once_with()

    def test_rest_and_json(self):
        rest = load_plugin_module('rest_under_test', 'plugins/rest/rest.py')
        importer = rest.RestImport.__new__(rest.RestImport)
        importer.config = dict(self.CONFIG, hostname_field='host')
        fake = FakeHosts()
        with with_hosts(fake), patch('builtins.print'):
            importer.import_hosts([{'host': 'S1-HVL01', 'ip': '10.1.1.10'}])
        self.assert_three_devices(fake, {'ip': '10.1.1.10'})

    def test_csv(self):
        csv_module = load_plugin_module('csv_under_test', 'plugins/csv/csv.py')
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False,
                                         encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle, delimiter=';')
            writer.writerows([['host', 'ip'], ['S1-HVL01', '10.1.1.10']])
        self.addCleanup(os.unlink, handle.name)
        importer = csv_module.CSV.__new__(csv_module.CSV)
        importer.config = dict(self.CONFIG, path=handle.name, encoding='utf-8',
                               delimiter=';', hostname_field='host')
        importer.log_details = []
        importer.get_unique_id = lambda: 'run1'
        fake = FakeHosts()
        with with_hosts(fake), patch('builtins.print'):
            importer.import_hosts()
        self.assert_three_devices(fake, {'ip': '10.1.1.10'})
        self.assertIn(('num_saved', '3'), importer.log_details)

    def test_a_device_another_master_owns_is_left_alone(self):
        rest = load_plugin_module('rest_under_test', 'plugins/rest/rest.py')
        importer = rest.RestImport.__new__(rest.RestImport)
        importer.config = dict(self.CONFIG, hostname_field='host')
        fake = FakeHosts(owned_by_other={'S1-RTR01'})
        with with_hosts(fake), patch('builtins.print'):
            importer.import_hosts([{'host': 'S1-HVL01'}])
        fake.hosts['S1-RTR01'].save.assert_not_called()
        fake.hosts['S1-HVL01'].save.assert_called_once_with()
        fake.hosts['S1-SW01'].save.assert_called_once_with()

    def test_a_plain_rewrite_imports_one_host_as_before(self):
        rest = load_plugin_module('rest_under_test', 'plugins/rest/rest.py')
        importer = rest.RestImport.__new__(rest.RestImport)
        importer.config = {'id': 'acc1', 'name': 'stores', 'hostname_field': 'host',
                           'rewrite_hostname': '{{ HOSTNAME }}.example.com'}
        fake = FakeHosts()
        with with_hosts(fake), patch('builtins.print'):
            importer.import_hosts([{'host': 'srv01,a'}])
        self.assertEqual(list(fake.hosts), ['srv01,a.example.com'])


class RunInventoryTest(unittest.TestCase):
    """run_inventory lands on the hosts the import created, rewriting once"""

    def setUp(self):
        # The bootstrap stubs the inventory helper; load the real one with
        # just enough of its imports around it
        core = types.ModuleType('syncerapi.v1.core')
        core.app_config = {'LOWERCASE_HOSTNAMES': False}
        get_account = types.ModuleType('application.helpers.get_account')
        get_account.account_allows = lambda config, what: True
        modules = {'syncerapi.v1.core': core,
                   'application.helpers.get_account': get_account}
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.inventory = load_plugin_module('inventory_under_test', 'helpers/inventory.py')
        self.inventorize_host = MagicMock()
        self.inventory.inventorize_host = self.inventorize_host

    def run_inventory(self, config, objects):
        fake = FakeHosts()
        for name in ['S1-HVL01', 'S1-RTR01', 'S1-SW01', 'srv01.example.com']:
            fake.get_host(name)
        self.inventory.Host = types.SimpleNamespace(get_host=fake.get_host)
        with with_hosts(fake), patch('builtins.print'):
            self.inventory.run_inventory(dict(config, inventorize_key='inv'), objects)
        return fake, [call.args[0] for call in self.inventorize_host.call_args_list]

    def test_every_device_of_the_record_is_inventorized(self):
        fake, hosts = self.run_inventory({'rewrite_hostname': STORE_TEMPLATE},
                                         [('S1-HVL01', {'ip': '1'})])
        self.assertEqual(hosts, [fake.hosts[x] for x in ['S1-HVL01', 'S1-RTR01', 'S1-SW01']])

    def test_the_rewrite_is_applied_once(self):
        # It used to run in the importer and again in run_inventory,
        # which made srv01.example.com.example.com of it
        fake, hosts = self.run_inventory({'rewrite_hostname': '{{ HOSTNAME }}.example.com'},
                                         [('srv01', {})])
        self.assertEqual(hosts, [fake.hosts['srv01.example.com']])


class EveryImporterUsesTheHelperTest(unittest.TestCase):
    """
    No importer turns a record into hosts on its own, so a list renders
    into several hosts everywhere, also in importers added later.
    """

    # Modules that create or look up hosts without being a record import
    NOT_AN_IMPORT = {
        # Export side: looks up hosts the Syncer already has
        'application/plugins/checkmk/syncer.py',
        # Creates the hosts typed into the data quality page
        'application/plugins/checkmk/data_quality.py',
        # Checkmk sites and JDisc applications become objects, not hosts
        'application/plugins/checkmk/sites.py',
        'application/plugins/jdisc/jdisc.py',
        # Checkmk 1.x Web API importer, it carries no attributes to rewrite with
        'application/plugins/checkmk/import_v1.py',
    }
    # The parent rewrite of ServiceNow child tables names an existing host
    OWN_REWRITE = {'application/plugins/servicenow/syncer.py'}

    CREATES_HOSTS = re.compile(r'Host\.get_host\(|\.update_host\(|=\s*Host\(\)')

    @staticmethod
    def plugin_sources():
        for base in ('application/plugins', 'syncerapi'):
            for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, base)):
                if os.sep + 'tests' in root:
                    continue
                for name in files:
                    if name.endswith('.py'):
                        path = os.path.join(root, name)
                        with open(path, encoding='utf-8') as handle:
                            yield os.path.relpath(path, REPO_ROOT), handle.read()

    def test_no_importer_rewrites_a_hostname_itself(self):
        offenders = [path for path, source in self.plugin_sources()
                     if 'rewrite_hostname(' in source and path not in self.OWN_REWRITE]
        self.assertEqual(offenders, [])

    def test_every_importer_goes_through_the_helper(self):
        offenders = [path for path, source in self.plugin_sources()
                     if self.CREATES_HOSTS.search(source)
                     and 'application.helpers.import_hostnames' not in source
                     and path not in self.NOT_AN_IMPORT]
        self.assertEqual(offenders, [])

    def test_the_inventory_goes_through_the_helper(self):
        path = os.path.join(REPO_ROOT, 'application', 'helpers', 'inventory.py')
        with open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('import_hostnames(', source)
        self.assertNotIn('rewrite_hostname(', source)
