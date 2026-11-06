"""
The i-doit export must recognize every existing object, or it creates a
duplicate in each run. The API is faked, it filters like cmdb.objects.read.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVER = 'C__OBJTYPE__SERVER'
OBJECTS = [
    {'id': 1, 'title': 'plain', 'type': SERVER, 'cmdb_status': 6},
    {'id': 2, 'title': 'switch', 'type': 'C__OBJTYPE__SWITCH', 'cmdb_status': 6},
    {'id': 3, 'title': 'planned', 'type': SERVER, 'cmdb_status': 8},
    {'id': 4, 'title': 'unmonitored', 'type': SERVER, 'cmdb_status': 6,
     'monitoring_active_value': '0'},
]


def load_module():
    spec = importlib.util.spec_from_file_location(
        'idoit_syncer_under_test',
        os.path.join(REPO_ROOT, 'application', 'plugins', 'idoit', 'syncer.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExportTest(unittest.TestCase):

    def setUp(self):
        self.module = load_module()
        self.created = []
        printer = patch('builtins.print')
        printer.start()
        self.addCleanup(printer.stop)

    def fake_api(self, json_data):
        if json_data['method'] == 'cmdb.objects.read':
            wanted = json_data['params']['filter'].get('type')
            return {'result': [obj for obj in OBJECTS
                               if wanted is None or obj['type'] == wanted]}
        self.created.append(json_data['params']['title'])
        return {'result': {}}

    def run_export(self, hostnames, list_rows=()):
        syncer = self.module.SyncIdoit.__new__(self.module.SyncIdoit)
        syncer.config = {'api_token': 't', 'language': 'en',
                         'filter_cmdb_status': '6', 'filter_monitoring_status': True}
        syncer.request = self.fake_api
        syncer.get_attributes = lambda _host, _cache: {'all': {}}
        syncer.get_host_data = lambda _host, _attributes: {}
        syncer.export_list_rows = lambda export, named: [export(row) for row in list_rows]
        hosts = [MagicMock(hostname=name) for name in hostnames]
        for host, name in zip(hosts, hostnames):
            host.hostname = name
        with patch.object(self.module.Host, 'get_export_hosts', return_value=hosts,
                          create=True):
            syncer.export_hosts()

    def test_existing_objects_are_not_created_again(self):
        self.run_export(['plain', 'switch', 'planned', 'unmonitored'])
        self.assertEqual(self.created, [])

    def test_a_missing_object_is_created_once(self):
        row = MagicMock(rule='list', outcomes={})
        row.name = 'new'
        self.run_export(['new'], [row])
        self.assertEqual(self.created, ['new'])


if __name__ == '__main__':
    unittest.main()
