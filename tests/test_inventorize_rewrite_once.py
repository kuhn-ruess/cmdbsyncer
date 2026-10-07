"""
Inventorize applies rewrite_hostname exactly once

The inventorize paths of CSV, REST, YML, MySQL, ODBC, JDisc and LDAP
rewrote the hostname themselves and run_inventory rewrote it again, so a
template that appends a domain looked for srv01.example.com.example.com
and missed the host the import had created. Every importer is run here
through its real inventorize path into the real run_inventory.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import csv
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

from tests import real_render_jinja

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEMPLATE = '{{ HOSTNAME }}.example.com'
CONFIG = {'id': 'acc1', 'name': 'servers', 'rewrite_hostname': TEMPLATE,
          'inventorize_key': 'inv'}


def load_module(name, relative_path):
    """A fresh copy of a source file, so patching it touches no other test"""
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(REPO_ROOT, 'application', relative_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeHost:
    """Host with the real rewrite, and a lookup that notes every name"""

    def __init__(self):
        self.looked_up = []

    @staticmethod
    def rewrite_hostname(old_name, template, attributes):
        return real_render_jinja(template, HOSTNAME=old_name, **attributes)

    def get_host(self, name, create=True):
        self.looked_up.append(name)
        host = Mock(name=name)
        host.hostname = name
        host.set_account.return_value = create
        return host


class InventorizeRewriteOnceTest(unittest.TestCase):

    def setUp(self):
        self.host = FakeHost()
        # The bootstrap stubs the inventory helper and leaves out a few
        # modules the importers need; put just enough of them around
        core = types.ModuleType('syncerapi.v1.core')
        core.app_config = {'LOWERCASE_HOSTNAMES': False}
        core.logger = MagicMock()
        core.Plugin = sys.modules['application.modules.plugin'].Plugin
        get_account = types.ModuleType('application.helpers.get_account')
        get_account.account_allows = lambda config, what: True
        get_account.get_account_by_name = MagicMock()
        jdisc_package = types.ModuleType('application.plugins.jdisc')
        jdisc_package.__path__ = []
        jdisc = types.ModuleType('application.plugins.jdisc.jdisc')
        jdisc.JDisc = type('JDisc', (), {})
        modules = {'syncerapi.v1.core': core,
                   'syncerapi.v1.inventory': types.ModuleType('syncerapi.v1.inventory'),
                   'application.helpers.get_account': get_account,
                   'application.plugins.jdisc': jdisc_package,
                   'application.plugins.jdisc.jdisc': jdisc}
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        sys.modules['application.helpers.sql'] = load_module('application.helpers.sql',
                                                             'helpers/sql.py')
        self.inventory = load_module('inventory_under_test', 'helpers/inventory.py')
        sys.modules['syncerapi.v1.inventory'].run_inventory = self.inventory.run_inventory
        self.inventory.Host = self.host
        self.inventory.inventorize_host = MagicMock()
        printer = patch('builtins.print')
        printer.start()
        self.addCleanup(printer.stop)

    def plugin(self, name, relative_path):
        """The plugin module, wired to the real run_inventory and the fake Host"""
        module = load_module(name, relative_path)
        module.Host = self.host
        module.run_inventory = self.inventory.run_inventory
        return module

    def assert_rewritten_once(self):
        self.assertEqual(self.host.looked_up, ['srv01.example.com'])
        self.inventory.inventorize_host.assert_called_once()

    def test_run_inventory_rewrites_the_source_name(self):
        self.inventory.run_inventory(dict(CONFIG), [('srv01', {})])
        self.assert_rewritten_once()

    def test_csv(self):
        module = self.plugin('csv_under_test', 'plugins/csv/csv.py')
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False,
                                         encoding='utf-8', newline='') as handle:
            csv.writer(handle, delimiter=';').writerows([['host', 'ip'], ['srv01', '10.1.1.1']])
        self.addCleanup(os.unlink, handle.name)
        importer = module.CSV.__new__(module.CSV)
        importer.config = dict(CONFIG, path=handle.name, encoding='utf-8',
                               delimiter=';', hostname_field='host')
        importer.log_details = []
        importer.inventorize_hosts()
        self.assert_rewritten_once()

    def test_rest(self):
        module = self.plugin('rest_under_test', 'plugins/rest/rest.py')
        importer = module.RestImport.__new__(module.RestImport)
        importer.config = dict(CONFIG, hostname_field='host')
        importer.inventorize_objects([{'host': 'srv01'}])
        self.assert_rewritten_once()

    def test_yml(self):
        module = self.plugin('yml_under_test', 'plugins/yml/yml.py')
        importer = module.YMLSyncer.__new__(module.YMLSyncer)
        importer.config = dict(CONFIG)
        importer.inventorize_objects([{'hostname': 'srv01'}])
        self.assert_rewritten_once()

    def test_mysql(self):
        module = self.plugin('mysql_under_test', 'plugins/mysql/mysql.py')
        module.get_account_by_name = lambda account: dict(
            CONFIG, address='db', username='u', password='p', database='d',
            fields='host,ip', table='hosts', hostname_field='host')
        module.custom_query_allow_ddl = lambda config: False
        module.build_select_query = MagicMock()
        module.mysql = MagicMock()
        cursor = module.mysql.connector.connect.return_value.cursor.return_value
        cursor.fetchall.return_value = [('srv01', '10.1.1.1')]
        module.mysql_inventorize('servers')
        self.assert_rewritten_once()

    def test_odbc(self):
        module = self.plugin('pyodbc_under_test', 'plugins/pyodbc/pyodbc.py')
        importer = module.ODBC.__new__(module.ODBC)
        importer.config = dict(CONFIG, hostname_field='host')
        importer._innter_sql = lambda: iter([('srv01', {'host': 'srv01'})])  # pylint: disable=protected-access
        importer.sql_inventorize()
        self.assert_rewritten_once()

    def test_jdisc(self):
        module = self.plugin('application.plugins.jdisc.devices', 'plugins/jdisc/devices.py')
        importer = module.JdiscDevices.__new__(module.JdiscDevices)
        importer.config = dict(CONFIG)
        importer.run_query = lambda: {'devices': {'findAll': [{'name': 'srv01'}]}}
        importer.inventorize()
        self.assert_rewritten_once()

    def ldap_module(self):
        module = self.plugin('ldap_under_test', 'plugins/ldap/ldap.py')
        module._check_address = lambda config: True  # pylint: disable=protected-access
        module._connect = lambda config: object()  # pylint: disable=protected-access
        module._search = lambda connect, config: [  # pylint: disable=protected-access
            ('cn=srv01,dc=example', {'cn': [b'srv01']})]
        return module, dict(CONFIG, hostname_field='cn', encoding='utf-8')

    def test_ldap_inventorize(self):
        module, config = self.ldap_module()
        # What ldap_inventorize hands to run_inventory
        self.inventory.run_inventory(config, module._inner_import(config))  # pylint: disable=protected-access
        self.assert_rewritten_once()

    def test_ldap_import_still_rewrites(self):
        module, config = self.ldap_module()
        module.get_account_by_name = lambda account: config
        module.ldap_import('servers')
        self.assertEqual(self.host.looked_up, ['srv01.example.com'])

    def test_ldap_search_shows_the_rewritten_name(self):
        module, config = self.ldap_module()
        hostname, _labels = module.parse_object('cn=srv01,dc=example',
                                                {'cn': [b'srv01']}, config)
        self.assertEqual(hostname, 'srv01.example.com')


if __name__ == '__main__':
    unittest.main()
