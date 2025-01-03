"""
Create Devices in Netbox
"""
#pylint: disable=no-member, too-many-locals, import-error

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from application.modules.netbox.netbox import SyncNetbox
from application import logger

from application.models.host import Host


class SyncVirtualMachines(SyncNetbox):
    """
    Netbox Virutal Machine Operations
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
            'cluster': {
                'type': 'virtualization.clusters',
                'has_slug': True,
            },
            'role': {
                'type': 'dcim.device-roles',
                 'has_slug' : True,
            },
            'platform': {
                'type': 'dcim.platforms',
                 'has_slug' : True,
            },
            'primary_ip4' : {
                'type': 'ipam.ip-addresses',
                'has_slug': False,
                'name_field': 'address',
            }
        }

#   .--- Sync Virtual Machines
    def sync_virtualmachines(self):
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
            task1 = progress.add_task("Updating Objects", total=total)

            current_nb_objects = self.nb.virtualization.virtual_machines

            for db_object in db_objects:
                hostname = db_object.hostname
                try:
                    all_attributes = self.get_host_attributes(db_object, 'netbox_hostattribute')
                    if not all_attributes:
                        progress.advance(task1)
                        continue
                    cfg = self.get_host_data(db_object, all_attributes['all'])
                    if not cfg:
                        continue

                    object_name = hostname
                    query = {
                        'name': object_name,
                    }
                    logger.debug(f"Object Filter Query: {query}")
                    if current_obj := current_nb_objects.get(**query):
                        if payload := self.get_update_keys(current_obj, cfg):
                            self.console(f"* Update Object: {object_name} {payload}")
                            current_obj.update(payload)
                        else:
                            self.console(f"* Object {object_name} already up to date")
                    else:
                        ### Create
                        self.console(f"* Create Object {object_name}")
                        payload = self.get_update_keys(False, cfg)
                        payload['name'] = object_name
                        for what in ['primary_ip4', 'primary_ip4']:
                            if what in payload:
                                del payload[what]
                        logger.debug(f"Create Payload: {payload}")
                        current_obj = self.nb.virtualization.virtual_machines.create(payload)
                except Exception as error:
                    if self.debug:
                        raise
                    self.log_details.append((f'export_error {hostname}', str(error)))
                    print(f" Error in process: {error}")
                if current_obj:
                    attr_name = f"{self.config['name']}_virtualmachine_id"
                    db_object.set_inventory_attribute(attr_name, current_obj.id)

                progress.advance(task1)
#.
