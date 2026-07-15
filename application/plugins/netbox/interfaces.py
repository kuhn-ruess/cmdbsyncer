"""
Interface Syncronisation
"""
from collections import defaultdict

from application import logger
from application.models.host import Host

from .netbox import SyncNetbox
from .utils import make_progress, parse_import_filter


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
        # pylint: disable=too-many-locals,too-many-branches
        # pylint: disable=too-many-statements,too-many-nested-blocks
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        with make_progress() as progress:
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

                    all_attributes = self.get_attributes(db_object, 'netbox')
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
                        sub_fields = cfg_interface['sub_fields']
                        ipv4 = sub_fields.get('ipv4_addresses', {}).get('value')
                        ipv6 = sub_fields.get('ipv6_addresses', {}).get('value')
                        if not ipv4 and not ipv6:
                            continue
                        cfg_interface['fields'] = self.fix_values(cfg_interface['fields'])
                        logger.debug("Working with %s", cfg_interface)
                        interface_name = cfg_interface['fields']['name']['value']
                        interface_query = {
                            'device': hostname,
                            'name': interface_name,
                        }
                        logger.debug("%s Interface Filter Query: %s", mode, interface_query)
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
                                        sub_fields['netbox_device_id']['value']
                            logger.debug("Create Payload: %s", payload)
                            if mode == 'dcim':
                                interface = self.nb.dcim.interfaces.create(payload)
                            elif mode == 'virtualization':
                                interface = self.nb.virtualization.interfaces.create(payload)


                        port_infos.append({
                            'port_name': cfg_interface['fields']['name']['value'],
                            'netbox_if_id': interface.id,
                            'ipv4_addresses': ipv4,
                            'ipv6_addresses': ipv6,
                        })
                except Exception as error:  # pylint: disable=broad-exception-caught
                    if self.debug:
                        raise
                    self.log_details.append((f'export_error {hostname}', str(error)))
                    self.console(f" Error in process: {error}")


                progress.advance(task1)
                attr_name = f"{self.config['name']}_{mode}_interfaces"
                db_object.set_inventory_attribute(attr_name, port_infos)


#   .--- Import Interfaces
    def import_interfaces(self, mode='dcim'):
        """
        Import Interfaces from Netbox, analogous to the device / VM import.

        By default each host's interfaces (including their assigned IP
        addresses) are stored on the matching Host's inventory. When the
        account custom field ``import_as_hosts`` is set, every interface is
        imported as its own Host object instead, so it can be exported again
        like any other host.
        """
        per_host = self._collect_import_interfaces(mode)
        if self.config.get('import_as_hosts'):
            self._import_interfaces_as_hosts(per_host)
        else:
            self._import_interfaces_to_inventory(per_host, mode)

    def _collect_import_interfaces(self, mode):
        """
        Sweep Netbox once for all interfaces and once for their assigned IP
        addresses, returning them grouped by their parent host name. Two
        paginated passes keep this at two API round-trips instead of one call
        per interface.
        """
        if mode == 'dcim':
            source_interfaces = self.nb.dcim.interfaces
            parent_attr = 'device'
            assigned_object_type = 'dcim.interface'
        else:
            source_interfaces = self.nb.virtualization.interfaces
            parent_attr = 'virtual_machine'
            assigned_object_type = 'virtualization.vminterface'

        interface_filter = {}
        if import_filter := self.config.get('import_filter'):
            interface_filter = parse_import_filter(import_filter)

        per_host = defaultdict(list)
        by_id = {}
        for interface in source_interfaces.filter(**interface_filter):
            parent = getattr(interface, parent_attr, None)
            if not parent or not getattr(parent, 'name', None):
                continue
            entry = self._interface_entry(interface)
            by_id[interface.id] = entry
            per_host[parent.name].append(entry)

        self._attach_ip_addresses(assigned_object_type, by_id)
        return per_host

    @staticmethod
    def _interface_entry(interface):
        """
        Build a serialisable dict of an interface's own fields. Virtualization
        interfaces have no ``type`` field, so every attribute is read via
        getattr and both endpoints share this code.
        """
        if_type = getattr(interface, 'type', None)
        return {
            'name': interface.name,
            'type': str(if_type) if if_type else None,
            'enabled': bool(getattr(interface, 'enabled', False)),
            'mtu': getattr(interface, 'mtu', None),
            'mac_address': getattr(interface, 'mac_address', None),
            'description': getattr(interface, 'description', None),
            'netbox_if_id': interface.id,
            'ipv4_addresses': [],
            'ipv6_addresses': [],
        }

    def _attach_ip_addresses(self, assigned_object_type, by_id):
        """Attach every interface-assigned IP to its interface entry."""
        assigned_ips = self.nb.ipam.ip_addresses.filter(
            assigned_object_type=assigned_object_type)
        for ip_addr in assigned_ips:
            entry = by_id.get(ip_addr.assigned_object_id)
            if not entry:
                continue
            if getattr(ip_addr.family, 'value', None) == 6:
                entry['ipv6_addresses'].append(ip_addr.address)
            else:
                entry['ipv4_addresses'].append(ip_addr.address)

    def _import_interfaces_to_inventory(self, per_host, mode):
        """Store each host's interfaces on the host's inventory."""
        rewrite = self.config.get('rewrite_hostname')
        attr_name = f"{self.config['name']}_{mode}_interfaces_import"
        with make_progress() as progress:
            self.console = progress.console.print
            task = progress.add_task("Importing Interfaces", total=len(per_host))
            for parent_name, port_infos in per_host.items():
                hostname = parent_name
                if rewrite:
                    hostname = Host.rewrite_hostname(hostname, rewrite, {})
                db_object = Host.get_host(hostname, create=False)
                if db_object:
                    self.console(f"* {hostname}: {len(port_infos)} interfaces imported")
                    db_object.set_inventory_attribute(attr_name, port_infos)
                else:
                    self.console(f"* Skip {hostname}: host not found in Syncer")
                progress.advance(task)

    def _import_interfaces_as_hosts(self, per_host):
        """
        Import every interface as its own Host object so it can be exported
        again like any other host.
        """
        import_id = self.get_unique_id()
        rewrite = self.config.get('rewrite_hostname')
        total = sum(len(infos) for infos in per_host.values())
        with make_progress() as progress:
            self.console = progress.console.print
            task = progress.add_task("Importing Interfaces as Hosts", total=total)
            for parent_name, port_infos in per_host.items():
                for port in port_infos:
                    self._import_interface_host(parent_name, port, import_id, rewrite)
                    progress.advance(task)
        if extra_filter := self.config.get('delete_host_if_not_found_on_import'):
            Host.delete_host_not_found_on_import(self.config['name'], import_id, extra_filter)

    def _import_interface_host(self, parent_name, port, import_id, rewrite):
        """Create / update a single interface as a Host object."""
        if not port['name']:
            return
        hostname = f"{parent_name}/{port['name']}"
        labels = dict(port, parent_host=parent_name)
        if rewrite:
            hostname = Host.rewrite_hostname(hostname, rewrite, labels)
        host_obj = Host.get_host(hostname)
        self.console(f"* Import Interface Host {hostname}")
        host_obj.update_host(labels)
        if host_obj.set_account(account_dict=self.config, import_id=import_id):
            host_obj.save()
#.


class SyncVirtInterfaces(SyncInterfaces):
    """
    Class needed cause of cache feature
    """
