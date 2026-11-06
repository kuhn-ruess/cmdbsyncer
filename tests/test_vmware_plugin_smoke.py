"""
VMware plugin without a vCenter: the session and a VM that goes away.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from unittest.mock import MagicMock, patch

from application.plugins.vmware import custom_attributes, vmware

# The session on vCenter is closed at the end
plugin = vmware.VMWareVcenterPlugin.__new__(vmware.VMWareVcenterPlugin)
plugin.config = {'address': 'vcenter.example.com', 'username': 'u', 'password': 'p'}
plugin.verify = True
plugin.debug = False
with patch.object(vmware, 'SmartConnect', create=True) as smart_connect, \\
        patch.object(vmware, 'Disconnect', create=True) as disconnect, \\
        patch('atexit.register') as register:
    plugin.connect()
eq(register.call_args.args, (disconnect, smart_connect.return_value), 'session closed at exit')

# A VM going away costs only that VM
plugin = custom_attributes.VMwareCustomAttributesPlugin.__new__(
    custom_attributes.VMwareCustomAttributesPlugin)
plugin.config = {}
plugin.log_details = []
plugin.vcenter = MagicMock()
view = plugin.vcenter.RetrieveContent.return_value.viewManager
view.CreateContainerView.return_value.view = ['gone', 'there']


def reader(virtual_machine, _content):
    if virtual_machine == 'gone':
        raise RuntimeError('ManagedObjectNotFound')
    return {'name': virtual_machine}


with patch.object(custom_attributes, 'vim', MagicMock(), create=True):
    eq(plugin._collect(reader), [{'name': 'there'}], 'the other VM stays')
eq(plugin.log_details[0][0], 'error', 'the skipped VM is logged')

print('VMWARE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class VmwarePluginTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_vmware(self):
        """See the checks in SNIPPET."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('VMWARE_OK', result.stdout)
