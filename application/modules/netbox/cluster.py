"""
Create Devices in Netbox
"""
#pylint: disable=no-member, too-many-locals, import-error

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from application.modules.netbox.netbox import SyncNetbox
from application import logger

from application.models.host import Host


class SyncCluster(SyncNetbox):
    """
    Netbox Device Operations
    """
    console = None

    @staticmethod
    def get_field_config():
        """
        Return Fields needed for Devices
        """
        return {
            'site': {
                'type': 'dcim.sites',
                'has_slug': True,
            },
            'type': {
                'type': 'virtualization.cluster-types',
                'has_slug': True,
            },
        }

#   .--- Sync Cluster
    def sync_clusters(self):
        """
        Update Devices Table in Netbox
        """
        current_netbox_clusters = self.nb.virtualization.clusters
        self.sync_generic('Cluster', current_netbox_clusters, 'name')
#.
