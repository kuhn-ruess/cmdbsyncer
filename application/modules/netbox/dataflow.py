"""
IPAM Syncronisation
"""
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host


class SyncDataFlow(SyncNetbox):
    """
    Netbox Data Flow
    """
    console = None

    def sync_dataflow(self):
        """
        Sync Dataflow Addresses
        """
        # Get current IPs
        current_objects = self.nb.XXX

        print(current_objects)
        return

        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Updateing Objectst", total=total)
            for db_object in db_objects:
                hostname = db_object.hostname

                all_attributes = self.get_host_attributes(db_object, 'netbox_hostattribute')
                if not all_attributes:
                    progress.advance(task1)
                    continue
                field_cfgs = self.get_host_data(db_object, all_attributes['all'])

                for field_cfg in field_cfgs:
                    logger.debug(f"Working with {field_cfg}")
                    query = {
                    }
                    logger.debug(f"Filter Query: {query}")
                    if nb_object := current_objects.get(**query):
                        # Update
                        if payload := self.get_update_keys(nb_object, field_cfg):
                            self.console(f"* Update Object: ... on {hostname}")
                            nb_object.update(payload)
                        else:
                            self.console(f"* Already up to date ... on {hostname}")
                    else:
                        ### Create
                        self.console(f" * Create Object  on {hostname}")
                        payload = self.get_update_keys(False, field_cfg)
                        logger.debug(f"Create Payload: {payload}")

                        new_object = self.nb.XXX.create(payload)
                        print(new_object)
            progress.advance(task1)
