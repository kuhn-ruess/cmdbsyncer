"""
A failed export says nothing about a NetBox object: cleanup leaves it alone
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from application.plugins.netbox.devices import SyncDevices
from tests.test_import_archive_guard import load_module

DECOMMISSION = {'status': 'decommissioning'}


def netbox_object(name):
    item = MagicMock(status='Active')
    item.name = name

    def update(payload):
        if name == 'api-error' and payload != DECOMMISSION:
            raise ValueError('HTTP 500')

    item.update.side_effect = update
    return item


def host_data(db_host, _attributes):
    if db_host.hostname == 'rule-error':
        raise ValueError('broken rule')
    return {'ignore_host': db_host.hostname == 'ignored', 'fields': {}}


def devices_target():
    return (sys.modules[SyncDevices.__module__], SyncDevices, 'export_hosts',
            lambda client: client.dcim.devices)


def targets():
    virtual = load_module('application.plugins.netbox.virtualmachines',
                          'plugins/netbox/virtualmachines.py')
    return (
        devices_target(),
        (virtual, virtual.SyncVirtualMachines, 'sync_virtualmachines',
         lambda client: client.virtualization.virtual_machines),
    )


def run_export(target, hosts, netbox_names, rows=()):
    """Runs one export, returns the names cleanup decommissioned and the log"""
    module, cls, method, endpoint_of = target
    syncer = cls.__new__(cls)
    syncer.config = {'name': 'nb', 'settings': {}}
    syncer.name = 'netbox'
    syncer.account_id = 'acc1'
    syncer.debug = False
    syncer.log_details = []
    syncer.nb = MagicMock()
    endpoint = endpoint_of(syncer.nb)
    in_netbox = {name: netbox_object(name) for name in netbox_names}

    def lookup(name):
        return in_netbox.get(name)

    endpoint.get.side_effect = lookup
    endpoint.filter.return_value = list(in_netbox.values())

    db_objects = MagicMock()
    db_objects.count.return_value = len(hosts)
    db_objects.__iter__.return_value = iter(
        [MagicMock(hostname=name) for name in hosts])
    with patch.object(module, 'Host') as mock_host, \
            patch.object(module, 'Progress'), \
            patch.object(syncer, 'get_attributes', return_value={'all': {}}), \
            patch.object(syncer, 'get_host_data', side_effect=host_data), \
            patch.object(syncer, 'get_update_keys', return_value={'a': 1}), \
            patch.object(syncer, 'list_rows', return_value=list(rows)), \
            patch('application.modules.plugin.logger'), \
            patch('builtins.print'):
        mock_host.objects_by_filter.return_value = db_objects
        getattr(syncer, method)()
    decommissioned = sorted(name for name, item in in_netbox.items()
                            if item.update.call_args
                            and item.update.call_args.args[0] == DECOMMISSION)
    return decommissioned, [key for key, _value in syncer.log_details]


class TestCleanupAfterFailure(unittest.TestCase):

    def test_failed_host_stays_gone_host_goes(self):
        for target in targets():
            with self.subTest(target[1].__name__):
                decommissioned, log = run_export(
                    target,
                    ['healthy', 'api-error', 'rule-error'],
                    ['healthy', 'api-error', 'rule-error', 'gone'])
                self.assertEqual(decommissioned, ['gone'])
                self.assertEqual(log, ['export_error api-error',
                                       'export_error rule-error'])

    def test_failed_list_row_stays(self):
        row = SimpleNamespace(name='api-error', attributes={'all': {}},
                              outcomes={'fields': {}}, rule='rule', row_idx=0)
        for target in targets():
            with self.subTest(target[1].__name__):
                decommissioned, log = run_export(
                    target, [], ['api-error', 'gone'], [row])
                self.assertEqual(decommissioned, ['gone'])
                self.assertEqual(log, ['export_error api-error'])

    def test_ignored_device_is_still_decommissioned(self):
        decommissioned, _log = run_export(
            devices_target(), ['ignored'], ['ignored', 'gone'])
        self.assertEqual(decommissioned, ['gone', 'ignored'])
