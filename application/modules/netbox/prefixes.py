"""
Create Prefixes in Netbox
"""
#pylint: disable=no-member, too-many-locals, import-error

from application.modules.netbox.netbox import SyncNetbox

class SyncPrefixes(SyncNetbox):
    """
    Netbox Prefix Operations
    """
    console = None

#   .--- Sync Cluster
    def sync_prefixes(self):
        """
        Update Prefixes in Netbox
        """
        current_objects = self.nb.ipam.prefixes
        self.sync_generic('Prefix', current_objects, 'prefix', list_mode='prefixes')
#.
