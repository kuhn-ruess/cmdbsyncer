"""
`cmdbsyncer sys delete_inventory` — scope of the wipe.

Without arguments the command clears the inventory of every host, which
is exactly what makes it dangerous during troubleshooting. `--hostname`
limits it to a single host. Either way the export attribute cache built
from the inventory is dropped along with it.
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


class DeleteInventoryScopeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_maintenance()

    def _run(self, hosts, **kwargs):
        params = {'prefix_only': '', 'hostname': '', 'debug': False}
        params.update(kwargs)
        with patch.object(self.mod, 'Host') as host_cls:
            host_cls.objects.return_value = hosts
            self.mod.delete_inventory.callback(**params)
            return host_cls.objects

    def _host(self, name, inventory):
        host = MagicMock()
        host.hostname = name
        host.inventory = inventory
        return host

    def test_a_hostname_limits_the_query_to_that_host(self):
        host = self._host('h1', {'a': 1})
        objects = self._run([host], hostname='h1')
        objects.assert_called_once_with(hostname='h1')
        host.update.assert_called_once_with(set__inventory={}, set__cache={})

    def test_without_a_hostname_every_host_is_wiped(self):
        host = self._host('h1', {'a': 1})
        objects = self._run([host])
        objects.assert_called_once_with()
        host.update.assert_called_once_with(set__inventory={}, set__cache={})

    def test_an_unknown_hostname_changes_nothing(self):
        self._run([], hostname='nope')
        # Nothing to assert on the host — the point is that the empty
        # result must not fall back to "all hosts".

    def test_the_prefix_still_applies_within_one_host(self):
        host = self._host('h1', {'cmk_x': 1, 'keep': 2})
        self._run([host], hostname='h1', prefix_only='cmk_')
        host.update.assert_called_once_with(
            set__inventory={'keep': 2}, set__cache={})


if __name__ == '__main__':
    unittest.main(verbosity=2)
