"""
Create Devices in Netbox
"""
#pylint: disable=no-member, too-many-locals, import-error

from application.modules.netbox.netbox import SyncNetbox

from application.models.host import Host
from application.modules.debug import ColorCodes as CC


class SyncDevices(SyncNetbox):
    """
    Netbox Device Operations
    """
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
                'name_field': 'address',
            }
        }

#   .--- Export Devices
    def export_hosts(self):
        """
        Update Devices Table in Netbox
        """
        #pylint: disable=too-many-locals
        current_netbox_devices = self.nb.dcim.devices

        print(f"\n{CC.OKGREEN} -- {CC.ENDC}Start Sync")
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        counter = 0
        found_hosts = []
        for db_host in db_objects:
            try:
                hostname = db_host.hostname
                counter += 1

                all_attributes = self.get_host_attributes(db_host, 'netbox')
                if not all_attributes:
                    continue
                custom_rules = self.get_host_data(db_host, all_attributes['all'])

                if custom_rules.get('ignore_host'):
                    continue

                process = 100.0 * counter / total
                print(f"\n{CC.OKBLUE}({process:.0f}%){CC.ENDC} {hostname}")

                found_hosts.append(hostname)
                if device := current_netbox_devices.get(name=hostname):
                    # Update
                    if update_keys := self.get_update_keys(device, custom_rules):
                        print(f"{CC.OKBLUE} *{CC.ENDC} Update Device: {update_keys}")
                        device.update(update_keys)
                    else:
                        print(f"{CC.OKBLUE} *{CC.ENDC} Netbox already up to date")
                else:
                    ### Create
                    print(f"{CC.OKGREEN} *{CC.ENDC} Create Device")
                    payload = self.get_update_keys(False, custom_rules)
                    payload['name'] = hostname
                    # When we create, we don't have all rferences jet.
                    # So we need to delete now and update alter
                    for what in ['primary_ip4', 'primary_ip4']:
                        if what in payload:
                            del payload[what]
                    device = self.nb.dcim.devices.create(payload)

            except Exception as error:
                print(f" Error in process: {error}")
            attr_name = f"{self.config['name']}_device_id"
            db_host.set_inventory_attribute(attr_name, device.id)

        print(f"\n{CC.OKGREEN} -- {CC.ENDC}Cleanup")
        for device in current_netbox_devices.all():
            if device.name not in found_hosts:
                print(f"{CC.OKBLUE} *{CC.ENDC} Delete {device.name}")
                device.delete()
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
