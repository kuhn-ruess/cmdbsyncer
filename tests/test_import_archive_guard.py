"""
Only a clean import may archive the hosts it did not see
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import application.modules.plugin as plugin_module
from application.modules.plugin import Plugin
from application.plugins.netbox.devices import SyncDevices
from application.plugins.netbox.interfaces import SyncInterfaces

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = {'name': 'source', 'delete_host_if_not_found_on_import': 'labels__a:b'}


def load_module(name, relative_path):
    """A plugin module the test bootstrap doesn't load, for real"""
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(REPO_ROOT, 'application', relative_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def importer_of(cls, **config):
    importer = cls.__new__(cls)
    importer.config = {**CONFIG, **config}
    importer.log_details = []
    importer.debug = False
    importer.get_unique_id = lambda: 'run1'
    return importer


class GuardedImport(unittest.TestCase):
    """Runs an importer and tells whether it archived anything"""

    def setUp(self):
        patcher = patch.object(plugin_module, 'Host')
        self.host = patcher.start()
        self.addCleanup(patcher.stop)
        self.host.delete_host_not_found_on_import.return_value = 2
        printer = patch('builtins.print')
        printer.start()
        self.addCleanup(printer.stop)

    def assert_archived(self):
        self.host.delete_host_not_found_on_import.assert_called_once_with(
            'source', 'run1', 'labels__a:b')

    def assert_not_archived(self, importer, reason):
        self.host.delete_host_not_found_on_import.assert_not_called()
        self.assertIn(('ERROR', f'Hosts not archived: {reason}'), importer.log_details)


class ArchiveDecisionTest(GuardedImport):

    def test_a_clean_import_archives(self):
        self.assertEqual(
            importer_of(Plugin).archive_hosts_not_imported('run1', 3), 2)
        self.assert_archived()

    def test_an_error_prevents_it(self):
        importer = importer_of(Plugin)
        self.assertIsNone(importer.archive_hosts_not_imported('run1', 3, 1))
        self.assert_not_archived(importer, 'the import had 1 error(s)')

    def test_an_empty_import_prevents_it(self):
        importer = importer_of(Plugin)
        self.assertIsNone(importer.archive_hosts_not_imported('run1', 0))
        self.assert_not_archived(importer, 'the import delivered no hosts')

    def test_without_the_option_nothing_happens(self):
        importer = importer_of(Plugin, delete_host_if_not_found_on_import='')
        self.assertIsNone(importer.archive_hosts_not_imported('run1', 0, 1))
        self.host.delete_host_not_found_on_import.assert_not_called()
        self.assertEqual(importer.log_details, [])


class CsvImportTest(GuardedImport):

    def run_import(self, content, update_side_effect=None):
        module = load_module('csv_archive_under_test', 'plugins/csv/csv.py')
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False,
                                         encoding='utf-8', newline='') as handle:
            handle.write(content)
        self.addCleanup(os.unlink, handle.name)
        importer = importer_of(module.CSV, path=handle.name, encoding='utf-8',
                               delimiter=';', hostname_field='host')
        with patch.object(module, 'get_import_hosts',
                          side_effect=lambda name, *_args: [(name, MagicMock())]), \
                patch.object(module, 'update_import_host',
                             side_effect=update_side_effect, return_value=True):
            importer.import_hosts()
        return importer

    def test_clean_file(self):
        importer = self.run_import('host;ip\nsrv1;10.0.0.1\n')
        self.assert_archived()
        self.assertIn(('num_deleted', '2'), importer.log_details)

    def test_broken_row(self):
        importer = self.run_import('host;ip\nsrv1;10.0.0.1\nsrv2;10.0.0.2\n',
                                   [True, ValueError('broken')])
        self.assert_not_archived(importer, 'the import had 1 error(s)')
        self.assertNotIn('num_deleted', [key for key, _value in importer.log_details])

    def test_file_with_only_a_header(self):
        self.assert_not_archived(self.run_import('host;ip\n'),
                                 'the import delivered no hosts')



class NetboxImportTest(GuardedImport):
    """Devices and virtual machines share the shape of their import"""

    def run_import(self, target, objects, update_side_effect=None):
        module, cls, api = target
        importer = importer_of(cls)
        client = MagicMock()
        api(client).filter.return_value = objects
        importer.nb = client
        importer.handle_nb_attributes = lambda labels: {}
        with patch.object(module, 'get_import_hosts',
                          side_effect=lambda name, *_args: [(name, MagicMock())]), \
                patch.object(module, 'update_import_host',
                             side_effect=update_side_effect):
            importer.import_hosts()
        return importer

    @staticmethod
    def targets():
        virtual = load_module('application.plugins.netbox.virtualmachines',
                              'plugins/netbox/virtualmachines.py')
        return (
            (sys.modules[SyncDevices.__module__], SyncDevices,
             lambda client: client.dcim.devices),
            (virtual, virtual.SyncVirtualMachines,
             lambda client: client.virtualization.virtual_machines),
        )

    @staticmethod
    def objects(*names):
        result = []
        for name in names:
            item = type('NetboxObject', (), {})()
            item.name = name
            for what in ('has_details', 'api', 'default_ret', 'endpoint',
                         '_full_cache', '_init_cache'):
                setattr(item, what, None)
            result.append(item)
        return result

    def test_clean_import(self):
        for target in self.targets():
            with self.subTest(target[1].__name__):
                self.host.reset_mock()
                self.run_import(target, self.objects('a'))
                self.assert_archived()

    def test_failing_object(self):
        for target in self.targets():
            with self.subTest(target[1].__name__):
                self.host.reset_mock()
                importer = self.run_import(target, self.objects('a', 'b'),
                                           [None, ValueError('broken')])
                self.assert_not_archived(importer, 'the import had 1 error(s)')

    def test_no_objects(self):
        for target in self.targets():
            with self.subTest(target[1].__name__):
                self.host.reset_mock()
                importer = self.run_import(target, [])
                self.assert_not_archived(importer, 'the import delivered no hosts')

    def test_only_objects_without_a_name(self):
        for target in self.targets():
            with self.subTest(target[1].__name__):
                self.host.reset_mock()
                importer = self.run_import(target, self.objects(''))
                self.assert_not_archived(importer, 'the import delivered no hosts')


class NetboxInterfaceHostsTest(GuardedImport):

    def run_import(self, per_host):
        importer = importer_of(SyncInterfaces)
        importer._import_interface_host = MagicMock()  # pylint: disable=protected-access
        with patch('application.plugins.netbox.interfaces.make_progress', MagicMock()):
            importer._import_interfaces_as_hosts(per_host)  # pylint: disable=protected-access
        return importer

    def test_interfaces_found(self):
        self.run_import({'switch': [{'name': 'eth0'}]})
        self.assert_archived()

    def test_no_interfaces(self):
        self.assert_not_archived(self.run_import({}), 'the import delivered no hosts')


if __name__ == '__main__':
    unittest.main()
