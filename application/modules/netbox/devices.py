"""
Create Devices in Netbox
"""
#pylint: disable=no-member, too-many-locals, import-error
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application.modules.netbox.netbox import SyncNetbox

from application.models.host import Host
from application.modules.debug import ColorCodes as CC


class SyncDevices(SyncNetbox):
    """
    Netbox Device Operations
    """

    console = None
    set_syncer_id = True

    @staticmethod
    def get_field_config():
        """
        Return Fields needed for Devices
        """
        return {
            'manufacturer': {
                'type': 'dcim.manufacturers',
                'has_slug' : True,
            },
            'model': {
                'type': 'string',
            },
            'site': {
                'type': 'dcim.sites',
                'has_slug': True,
            },
            'device_type': {
                'type': 'dcim.device-types',
                'has_slug': True,
                'sub_fields' : ['model', 'manufacturer'],
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
                'name_field': 'id',
            },
            'primary_ip6' : {
                'type': 'ipam.ip-addresses',
                'has_slug': False,
                'name_field': 'id',
            }
        }


    def get_ip_id(self, custom_rules, all_attributes, mode):
        """
        Search if the Host already has infos to his ip addreses saved
        """
        if primary_ip_obj := custom_rules['fields'].get(mode):
            needed_ip = primary_ip_obj['value']
            attr_name = f"{self.config['name']}_ips"
            if not attr_name in all_attributes['all']:
                del custom_rules['fields'][mode]
            else:
                new_value = False
                for ip in all_attributes['all'][attr_name]:
                    if ip['address'] == needed_ip:
                        new_value = ip['netbox_ip_id']
                        break
                if new_value:
                    custom_rules['fields'][mode]['value'] = new_value
                else:
                    del custom_rules['fields'][mode]
        return custom_rules

#   .--- Export Devices
    def export_hosts(self):
        """
        Update Devices Table in Netbox
        """
        #pylint: disable=too-many-locals
        current_netbox_devices = self.nb.dcim.devices


        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        found_hosts = []
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Updating Objects", total=total)
            for db_host in db_objects:
                try:
                    hostname = db_host.hostname
                    all_attributes = self.get_host_attributes(db_host, 'netbox')
                    if not all_attributes:
                        progress.advance(task1)
                        continue
                    custom_rules = self.get_host_data(db_host, all_attributes['all'])
                    if not custom_rules:
                        progress.advance(task1)
                        continue

                    if custom_rules.get('ignore_host'):
                        progress.advance(task1)
                        continue

                    custom_rules = self.get_ip_id(custom_rules, all_attributes, 'primary_ip4')
                    custom_rules = self.get_ip_id(custom_rules, all_attributes, 'primary_ip6')


                    found_hosts.append(hostname)
                    if device := current_netbox_devices.get(name=hostname):
                        # Update
                        if update_keys := self.get_update_keys(device, custom_rules,
                                                               ['primary_ip4', 'primary_ip6']):
                            self.console(f" * Update Device {hostname}: {update_keys}")
                            device.update(update_keys)
                        else:
                            self.console(f" * Already up to date {hostname}")
                    else:
                        ### Create
                        self.console(f" * Create Device {hostname}")
                        payload = self.get_update_keys(False, custom_rules)
                        payload['name'] = hostname
                        device = self.nb.dcim.devices.create(payload)

                except Exception as error:
                    if self.debug:
                        raise
                    self.log_details.append((f'export_error {hostname}', str(error)))
                    self.console(f" Error in process: {error}")
                progress.advance(task1)

                if device:
                    attr_name = f"{self.config['name']}_device_id"
                    db_host.set_inventory_attribute(attr_name, device.id)

        #print(f"\n{CC.OKGREEN} -- {CC.ENDC}Cleanup")
        #for device in current_netbox_devices.all():
        #    if device.name not in found_hosts:
        #        print(f"{CC.OKBLUE} *{CC.ENDC} Delete {device.name}")
        #        device.delete()
#.
#   .--- Import Devices
    def import_hosts(self):
        """
        Import Objects from Netbox to the Syncer
        """

        for device in self.nb.dcim.devices.all():
            hostname = device.name
            if not hostname:
                continue
            labels = device.__dict__
            for what in ['has_details', 'api',
                         'default_ret', 'endpoint',
                         '_full_cache', '_init_cache']:
                del labels[what]
            if 'rewrite_hostname' in self.config and self.config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname, self.config['rewrite_hostname'], labels)
            host_obj = Host.get_host(hostname)
            print(f"\n{CC.HEADER}Process Device: {hostname}{CC.ENDC}")
            host_obj.update_host(labels)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
#.
