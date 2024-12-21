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
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Updating Cluster", total=total)

            current_netbox_clusters = self.nb.virtualization.clusters

            for db_object in db_objects:
                hostname = db_object.hostname
                try:
                    all_attributes = self.get_host_attributes(db_object, 'netbox_hostattribute')
                    if not all_attributes:
                        progress.advance(task1)
                        continue
                    cfg_cluster = self.get_host_data(db_object, all_attributes['all'])
                    if not cfg_cluster:
                        continue

                    cluster_name = cfg_cluster['fields']['name']['value']
                    cluster_query = {
                        'name': cluster_name,
                    }
                    logger.debug(f"Cluster Filter Query: {cluster_query}")
                    if cluster := current_netbox_clusters.get(**cluster_query):
                        if payload := self.get_update_keys(cluster, cfg_cluster):
                            self.console(f"* Update Cluster: {cluster_name} {payload}")
                            cluster.update(payload)
                        else:
                            self.console(f"* Cluster {cluster_name} already up to date")
                    else:
                        ### Create
                        self.console(f"* Create Cluster {cluster_name}")
                        payload = self.get_update_keys(False, cfg_cluster)
                        logger.debug(f"Create Payload: {payload}")
                        cluster = self.nb.virtualization.clusters.create(payload)

                except Exception as error:
                    if self.debug:
                        raise
                    self.log_details.append((f'export_error {hostname}', str(error)))
                    print(f" Error in process: {error}")

                progress.advance(task1)
#.
