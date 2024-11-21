"""
Interface Syncronisation
"""
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from application import logger
from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host

class SyncInterfaces(SyncNetbox):
    """
    Interface Syncer
    """

    if_types = []
    console = None

    def fix_values(self, value_dict):
        """
        Fix invalid values
        """
        new_dict = {}
        for key, value in value_dict.items():
            if key == 'type':
                if value not in self.if_types:
                    value = 'other'
            new_dict[key] = value
        return new_dict


    def sync_interfaces(self):
        """
        Iterarte over objects and sync them to Netbox
        """
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Updating Interfaces for Devices", total=total)

            current_netbox_interfaces = self.nb.dcim.interfaces

            self.if_types = [x['value'] for x in self.nb.dcim.interfaces.choices()['type']]
            for db_object in db_objects:
                port_infos = []
                hostname = db_object.hostname

                all_attributes = self.get_host_attributes(db_object, 'netbox_hostattribute')
                if not all_attributes:
                    progress.advance(task1)
                    continue
                cfg_interfaces = self.get_host_data(db_object, all_attributes['all'])['interfaces']

                for cfg_interface in cfg_interfaces:
                    cfg_interface['fields'] = self.fix_values(cfg_interface['fields'])
                    logger.debug(f"Working with {cfg_interface}")
                    interface_query = {
                        'ip_address': cfg_interface['sub_fields']['ip_address'],
                        'device': hostname,
                        'name': cfg_interface['fields']['name'],
                    }
                    logger.debug(f"Interface Filter Query: {interface_query}")
                    if interface := current_netbox_interfaces.get(**interface_query):
                        # Update
                        if payload := self.get_update_keys(interface, cfg_interface):
                            self.console(f"* Update Interface: for {hostname} {payload}")
                            interface.update(payload)
                        else:
                            self.console("* Netbox already up to date")
                    else:
                        ### Create
                        self.console(f" * Create Interfaces for {hostname}")
                        payload = self.get_update_keys(False, cfg_interface)
                        payload['device'] = int(payload['device'])
                        logger.debug(f"Create Payload: {payload}")
                        interface = self.nb.dcim.interfaces.create(payload)

                    port_infos.append({
                        'port_name': cfg_interface['fields']['name'],
                        'netbox_if_id': interface.id,
                        'used_ip': cfg_interface['sub_fields']['ip_address'],
                    })

                progress.advance(task1)
                attr_name = f"{self.config['name']}_interfaces"
                db_object.set_inventory_attribute(attr_name, port_infos)
