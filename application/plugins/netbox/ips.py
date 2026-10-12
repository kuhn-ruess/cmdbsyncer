"""
IPAM Syncronisation
"""
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.models.host import Host
from .netbox import SyncNetbox


class SyncIPS(SyncNetbox):
    """
    IP Syncer
    """
    console = None

    @staticmethod
    def get_field_config():
        """
        Return Fields needed for Devices
        """
        return {
            'vrf': {
                'type': 'ipam.vrfs',
                'has_slug': False,
            },
        }

    def sync_ips(self):
        """
        Sync IP Addresses
        """
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Updating IPs", total=total)
            for db_object in db_objects:
                hostname = db_object.hostname

                all_attributes = self.get_attributes(db_object, 'netbox')
                if not all_attributes:
                    progress.advance(task1)
                    continue
                cfg_ips = self.get_host_data(db_object, all_attributes['all'])
                if 'ips' not in cfg_ips:
                    progress.advance(task1)
                    continue
                ip_infos = self.export_ips(hostname, cfg_ips['ips'])
                progress.advance(task1)
                attr_name = f"{self.config['name']}_ips"
                db_object.set_inventory_attribute(attr_name, ip_infos)

            # A row of a list rule describes IP addresses; its hostname or
            # name column names the device whose interface a name in
            # Assigned Object ID refers to. There is no host to note the
            # Netbox IDs on.
            self.export_list_rows(
                lambda row: self.export_ips(row.name, row.outcomes.get('ips', [])))

    def export_ips(self, hostname, cfg_ips):
        """
        Create or update the IP addresses of one host or list row
        (``hostname``, may be None for a row), return what was synced.
        """
        ip_infos = []
        for cfg_ip in cfg_ips:
            try:
                if 'ignore_ip' in cfg_ip['fields']:
                    continue
                if not 'addresses' in cfg_ip['fields']:
                    continue

                logger.debug("Working with %s", cfg_ip)
                # Delete Helper Field
                addresses = cfg_ip['fields']['addresses']['value']
                del cfg_ip['fields']['addresses']
                # Create Field to be used for the operation
                cfg_ip['fields']['address'] = {}
                assigned_obj = self.assigned_object_id(hostname, cfg_ip['fields'])
                for address in addresses:
                    if address in cfg_ip['ignore_list']:
                        continue
                    address = address.strip()
                    if not address:
                        continue
                    cfg_ip['fields']['address']['value'] = address
                    ip_infos.append(self.export_ip(hostname, cfg_ip, address, assigned_obj))
            except Exception as exp:  # pylint: disable=broad-exception-caught
                if self.debug:
                    raise
                self.console(f"Error with device: {exp}")
                self.log_details.append((f'export_error {hostname}', str(exp)))
        return ip_infos

    def export_ip(self, hostname, cfg_ip, address, assigned_obj):
        """
        Create or update one address, assigned to the interface with the
        ID ``assigned_obj``. Returns what was synced.
        """
        # @Todo: Try to use real pynetbox objects for the query
        ip_query = {
            'address': address,
        }
        logger.debug("IPAM IPS Filter %s Query: %s", hostname, ip_query)
        found = False
        if ips := self.nb.ipam.ip_addresses.filter(**ip_query):
            for ip in ips:
                if ip.assigned_object_id == assigned_obj:
                    found = ip
                    break
        if found:
            # Update
            if payload := self.get_update_keys(found, cfg_ip):
                self.console(f"* Update IP: for {address} on {hostname}")
                found.update(payload)
            else:
                self.console(f"* Nothing to do: {address} on {hostname}")
            return {'netbox_ip_id': found.id, 'address': address}

        ### Create
        self.console(f" * Create IP {address} on {hostname}")
        payload = self.get_update_keys(False, cfg_ip)
        logger.debug("Create Payload: %s", payload)
        ip = self.nb.ipam.ip_addresses.create(payload)
        return {'netbox_ip_id': ip.id, 'address': address}

    def assigned_object_id(self, hostname, fields):
        """
        The numeric ID of the interface the IP addresses are assigned to.
        Assigned Object ID is that ID, or the name of an interface of the
        device (or, with Assigned Object Type virtualization.vminterface,
        of the virtual machine) ``hostname``, looked up in Netbox. The
        fields get the numeric ID.
        """
        value = str(fields.get('assigned_object_id', {}).get('value') or '').strip()
        if not value:
            raise ValueError("No Assigned Object ID")
        if not value.isdigit():
            if not hostname:
                raise ValueError(f"Interface {value}: no hostname or name column "
                                 "names its device")
            object_type = fields.get('assigned_object_type', {}).get('value')
            if object_type == 'virtualization.vminterface':
                interface = self.nb.virtualization.interfaces.get(
                    virtual_machine=hostname, name=value)
            else:
                interface = self.nb.dcim.interfaces.get(device=hostname, name=value)
            if not interface:
                raise ValueError(f"Interface {value} of {hostname} not found in Netbox")
            value = str(interface.id)
        fields['assigned_object_id'] = {'value': value}
        return int(value)
