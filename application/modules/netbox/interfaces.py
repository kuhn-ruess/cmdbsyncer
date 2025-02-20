"""
Interface Syncronisation
"""
#pylint: disable = broad-exception-caught, too-many-locals, too-many-branches, too-many-statements, too-many-nested-blocks
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
        for key, data in list(value_dict.items()):
            if key == 'type':
                if data['value'] not in self.if_types:
                    data['value'] = 'other'
            value_dict[key] = data
        return value_dict


    def sync_interfaces(self, mode='dcim'):
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

            current_netbox_interfaces = False
            if mode == "dcim":
                current_netbox_interfaces = self.nb.dcim.interfaces
            elif mode == 'virtualization':
                current_netbox_interfaces = self.nb.virtualization.interfaces

            self.if_types = [x['value'] for x in self.nb.dcim.interfaces.choices()['type']]
            for db_object in db_objects:
                port_infos = []
                try:
                    hostname = db_object.hostname

                    all_attributes = self.get_host_attributes(db_object, 'netbox_hostattribute')
                    if not all_attributes:
                        progress.advance(task1)
                        continue
                    try:
                        cfg_interfaces = \
                                self.get_host_data(db_object, all_attributes['all'])['interfaces']
                    except KeyError:
                        progress.advance(task1)
                        continue

                    for cfg_interface in cfg_interfaces:
                        if not cfg_interface['sub_fields'].get('ipv4_addresses', {}).get('value') and \
                                not cfg_interface['sub_fields'].get('ipv6_addresses', {}).get('value'):
                            continue
                        cfg_interface['fields'] = self.fix_values(cfg_interface['fields'])
                        logger.debug(f"Working with {cfg_interface}")
                        interface_name = cfg_interface['fields']['name']['value']
                        interface_query = {
                            'device': hostname,
                            'name': interface_name,
                        }
                        logger.debug(f"{mode} Interface Filter Query: {interface_query}")
                        if interfaces := current_netbox_interfaces.filter(**interface_query):
                            for interface in interfaces:
                                # Update
                                if payload := self.get_update_keys(interface, cfg_interface):
                                    self.console(f"* Update {mode} Interface: "\
                                                 f"{interface_name} {payload}")
                                    interface.update(payload)
                                else:
                                    self.console(f"* Interface {interface} already up to date")
                        else:
                            ### Create
                            self.console(f"* Create {mode} Interface {interface_name}")
                            payload = self.get_update_keys(False, cfg_interface)
                            if payload.get('device'):
                                payload['device'] = \
                                        cfg_interface['sub_fields']['netbox_device_id']['value']
                            logger.debug(f"Create Payload: {payload}")
                            if mode == 'dcim':
                                interface = self.nb.dcim.interfaces.create(payload)
                            elif mode == 'virtualization':
                                interface = self.nb.virtualization.interfaces.create(payload)


                        port_infos.append({
                            'port_name': cfg_interface['fields']['name']['value'],
                            'netbox_if_id': interface.id,
                            'ipv4_addresses': \
                                    cfg_interface['sub_fields']['ipv4_addresses']['value'],
                            'ipv6_addresses': \
                                    cfg_interface['sub_fields']['ipv6_addresses']['value'],
                        })
                except Exception as error:
                    if self.debug:
                        raise
                    self.log_details.append((f'export_error {hostname}', str(error)))
                    self.console(f" Error in process: {error}")


                progress.advance(task1)
                attr_name = f"{self.config['name']}_{mode}_interfaces"
                db_object.set_inventory_attribute(attr_name, port_infos)


class SyncVirtInterfaces(SyncInterfaces):
    """
    Class needed cause of cache feature
    """
