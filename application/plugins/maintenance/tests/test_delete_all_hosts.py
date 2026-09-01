"""
`cmdbsyncer sys delete_all_hosts` — what the wipe covers.

Hosts flagged `no_autodelete` are the ones an admin deliberately kept
out of every automatic cleanup, so the command leaves them alone unless
`--include-protected` says otherwise. The folder-pool seats are given
back for exactly the hosts that are deleted, which is why the aggregate
that counts them has to carry the same filter as the delete itself.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import os
import re
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import click

from tests import _load_real_module


def _load_maintenance():
    """
    Load the maintenance plugin under the test bootstrap. It pulls in a
    handful of helpers the stubbed environment does not provide; they are
    unrelated to this command, so a MagicMock is enough.
    """
    # The bootstrap stubs the CLI group factory with a MagicMock, which
    # would turn every @command-decorated function into a mock. Hand out a
    # real click group so the commands stay callable.
    sys.modules['application.helpers.plugins'].register_cli_group = \
        lambda *_a, **_kw: click.Group('sys')
    for _ in range(25):
        try:
            return _load_real_module(
                'application.plugins.maintenance',
                os.path.join('plugins', 'maintenance', '__init__.py'))
        except ModuleNotFoundError as error:
            missing = str(error).split("'")[1]
            module = types.ModuleType(missing)
            module.__getattr__ = lambda _name: MagicMock()
            sys.modules[missing] = module
        except ImportError as error:
            match = re.match(r"cannot import name '(.+?)' from '(.+?)'",
                             str(error))
            if not match:
                raise
            name, module_name = match.groups()
            setattr(sys.modules[module_name], name, MagicMock())
    raise unittest.SkipTest("maintenance plugin could not be loaded")


class DeleteAllHostsScopeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_maintenance()

    def _run(self, answer='y', folders=None, pool=None, **kwargs):
        params = {'account': '', 'include_protected': False}
        params.update(kwargs)
        with patch.object(self.mod, 'Host') as host_cls, \
             patch.object(self.mod, 'CheckmkFolderPool') as pool_cls, \
             patch('builtins.input', return_value=answer):
            host_cls.objects.aggregate.return_value = folders or []
            pool_cls.objects.return_value.first.return_value = pool
            self.mod.delete_all_hosts.callback(**params)
            return host_cls, pool_cls

    @staticmethod
    def _delete_filter(host_cls):
        """The keyword filter the delete ran with."""
        return host_cls.objects.call_args.kwargs

    @staticmethod
    def _match(host_cls):
        """The $match stage of the folder-seat aggregate."""
        return host_cls.objects.aggregate.call_args.args[0]['$match']

    def test_protected_hosts_are_kept_by_default(self):
        host_cls, _pool = self._run()
        self.assertEqual(
            self._delete_filter(host_cls),
            {'object_type__ne': 'template', 'no_autodelete__ne': True})
        host_cls.objects.return_value.delete.assert_called_once_with()

    def test_include_protected_deletes_them_too(self):
        host_cls, _pool = self._run(include_protected=True)
        self.assertEqual(self._delete_filter(host_cls),
                         {'object_type__ne': 'template'})
        host_cls.objects.return_value.delete.assert_called_once_with()

    def test_templates_are_never_deleted(self):
        for include_protected in (False, True):
            host_cls, _pool = self._run(include_protected=include_protected)
            self.assertEqual(
                self._delete_filter(host_cls)['object_type__ne'], 'template')

    def test_account_filter_applies_to_both_stages(self):
        host_cls, _pool = self._run(account='cmdb', include_protected=True)
        self.assertEqual(self._delete_filter(host_cls)['source_account_name'],
                         'cmdb')
        self.assertEqual(self._match(host_cls)['source_account_name'], 'cmdb')

    def test_seat_count_uses_the_same_scope_as_the_delete(self):
        host_cls, _pool = self._run()
        self.assertEqual(self._match(host_cls)['no_autodelete'],
                         {'$ne': True})
        host_cls, _pool = self._run(include_protected=True)
        self.assertNotIn('no_autodelete', self._match(host_cls))

    def test_seats_are_given_back_to_the_pool(self):
        folder = MagicMock()
        folder.folder_seats_taken = 10
        _host_cls, _pool = self._run(
            folders=[{'_id': '/pool', 'count': 4}], pool=folder)
        self.assertEqual(folder.folder_seats_taken, 6)
        folder.save.assert_called_once_with()

    def test_more_hosts_than_seats_empties_the_pool(self):
        folder = MagicMock()
        folder.folder_seats_taken = 2
        self._run(folders=[{'_id': '/pool', 'count': 4}], pool=folder)
        self.assertEqual(folder.folder_seats_taken, 0)

    def test_a_folder_without_a_pool_is_skipped(self):
        host_cls, _pool = self._run(
            folders=[{'_id': '/plain', 'count': 4}], pool=None)
        # No pool to give seats back to, but the delete still runs.
        host_cls.objects.return_value.delete.assert_called_once_with()

    def test_anything_but_yes_deletes_nothing(self):
        host_cls, _pool = self._run(answer='n')
        host_cls.objects.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
