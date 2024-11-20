"""
Create Devices in Netbox
"""
#pylint: disable=no-member, too-many-locals, import-error

from application.modules.netbox.netbox import SyncNetbox

from application.models.host import Host
from application import logger
from application.modules.debug import ColorCodes as CC


class SyncDevices(SyncNetbox):
    """
    Netbox Device Operations
    """
    name = "Netbox Device Sync"
    source = "netbox_device_syn"

    def __init__(self, account):
        self.cache = {}

        super().__init__(account)

#   .-- Get Devices
    def get_devices(self, syncer_only=False):
        """
        Read full list of devices
        """
        print(f"{CC.OKGREEN} -- {CC.ENDC}Netbox: "\
              f"Read all devices (Filter only CMDB Syncer: {syncer_only})")
        url = 'dcim/devices/?limit=10000'
        if syncer_only:
            url += f"&cf_cmdbsyncer_id={self.config['_id']}"
        devices = self.request(url, "GET")
        return {x['display']:x for x in devices}
#.
#   .-- Create Netbox Sub Entry Types
    def create_sub_entry(self, endpoint, value, extra_infos=None):
        """
        Returns the Netbox Entry ID of given value
        directly or creates it first
        """
        endpoints = {
            'platform': {'url': 'dcim/platforms/',
                         'name_tag': 'name',
                         'fallback': 'CMDB Syncer Not defined',
                        },
            'device_type': {'url': 'dcim/device-types/',
                            'name_tag': 'model',
                            'sub_entries': ['manufacturer'],
                            'fallback': 'CMDB Syncer Not defined',
                           },
            'role': {'url': 'dcim/device-roles/',
                            'name_tag': 'name',
                            'fallback': 'CMDB Syncer Not defined',
                           },
            'manufacturer': {'url': 'dcim/manufacturers/',
                            'name_tag': 'name',
                            'fallback': 'CMDB Syncer Not defined',
                            },
            #'primary_ip4': {'url': 'ipam/ip-addresses/',
            #                'name_tag': 'address',
            #                'fallback': None,
            #                'split_needle': "/",
            #               },
            #'primary_ip6': {'url': 'ipam/ip-addresses/',
            #                'name_tag': 'address',
            #                'fallback': None,
            #               },
        }

        conf = endpoints[endpoint]
        if not value:
            fallback = conf['fallback']
            print(f"{CC.FAIL} *{CC.ENDC} {endpoint} invalid Value: {value}, Fallback to {fallback}")
            if not fallback:
                return None
            value = fallback



        print(f"{CC.OKCYAN} *{CC.ENDC} Attribute: {endpoint}:{value} configured for dynamic sync")
        if not self.cache.get(endpoint):
            print(f"{CC.OKGREEN} ** {CC.ENDC}build cache for {endpoint}")
            self.cache[endpoint] = {}
            for entry in self.request(conf['url'], "GET"):
                self.cache[endpoint][entry['display']] = entry['id']

        # FIND Data and Return in that case
        for entry_name, entry_id in self.cache[endpoint].items():
            if spliter := conf.get('split_needle'):
                entry_name = entry_name.split(spliter)[0]
            if entry_name == value:
                return entry_id

        # Create Entry
        payload = {
            conf['name_tag']: value,
            'slug': value.lower().replace(' ','_').replace(',', '_')
        }
        print(extra_infos)
        if extra_infos:
            for extra_key in conf.get('sub_entries', []):
                payload[extra_key] = \
                        self.create_sub_entry(extra_key,
                                              extra_infos.get(extra_key, 'Undefined'))

        response = self.request(conf['url'], "POST", payload)
        print(f"{CC.OKBLUE} *{CC.ENDC} New {endpoint} {value} created in Netbox")
        new_id = response.get('id')
        if not new_id:
            self.log_details.append(('error', f'Device Exception: {response.text}'))
            raise ValueError(f"Invalid Response from Netbox for {value}")
        self.cache[endpoint][value] = new_id
        return new_id
#.
#   .-- Get Device Payload
    def get_payload(self, db_host, custom_rules):
        """
        Build API Payload
        """
        payload = {
          "name": db_host.hostname,
          "device_type": 1,
          "role": 1,
          "tenant": None,
          "platform": None,
          "serial": None,
          #"asset_tag": "string",
          "site": 1,
          #"location": None,
          #"rack": None,
          #"position": 0.5,
          "face": None,
          #"parent_device": {
          #  "name": "string"
          #},
          #"status": "offline",
          #"airflow": "front-to-rear",
          "primary_ip4": None,
          "primary_ip6": None,
          #"cluster": 0,
          #"virtual_chassis": 0,
          #"vc_position": 255,
          #"vc_priority": 255,
          "comments": None,
          #"local_context_data": {},
          #"tags": [
          #  {
          #    "name": "string",
          #    "slug": "string",
          #    "color": "string"
          #  }
          #],
          #"custom_fields": {
          #}
        }


        payload['custom_fields'] = {
            'cmdbsyncer_id': str(self.config['_id']),
        }
        # Add Synced Variables or direct IDs
        for key, value in custom_rules.items():
            if key.endswith("_sync"):
                # Sync attribute by value of given tag
                # Needs to be first since we need nb_ in keyname
                endpoint_name = key[3:-5]
                payload[endpoint_name] = self.create_sub_entry(endpoint_name, value,
                                                               custom_rules['sub_values'])

            elif key.startswith('nb_'):
                key = key[3:]
                if key in payload:
                    payload[key] = value
            elif key == "custom_attributes":
                # Add Custom Variables
                for sub_key, sub_value in value:
                    payload['custom_fields'][sub_key] = sub_value

        # Cleanup Empty Keys
        keys = list(payload.keys())
        for key in keys:
            if not payload[key]:
                del payload[key]

        logger.debug(f"Payload: {payload}")
        return payload
#.
#   .--- Export Hosts
    def export_hosts(self):
        """
        Update Devices Table in Netbox
        """
        #pylint: disable=too-many-locals
        current_netbox_devices = self.get_devices(syncer_only=True)

        print(f"\n{CC.OKGREEN} -- {CC.ENDC}Start Sync")
        db_objects = Host.get_export_hosts()
        total = db_objects.count()
        counter = 0
        found_hosts = []
        for db_host in db_objects:
            hostname = db_host.hostname
            counter += 1

            all_attributes = self.get_host_attributes(db_host, 'netbox')
            if not all_attributes:
                continue
            custom_rules = self.get_host_data(db_host, all_attributes['all'])

            if custom_rules.get('ignore_host'):
                continue

            process = 100.0 * counter / total
            print(f"\n{CC.OKBLUE}({process:.0f}%){{CC.ENDC}} {hostname}")

            payload = self.get_payload(db_host, custom_rules)
            url = 'dcim/devices/'
            found_hosts.append(hostname)
            if hostname in current_netbox_devices:
                ## Update
                host_netbox_data = current_netbox_devices[hostname]
                host_netbox_id = host_netbox_data['id']
                if update_keys := self.need_update(host_netbox_data, payload,
                                                   custom_rules['do_not_update_keys']):
                    print(f"{CC.OKBLUE} *{CC.ENDC} Update Host")
                    url += f"{current_netbox_devices[hostname]['id']}/"
                    update_payload = {}
                    for key in update_keys:
                        update_payload[key] = payload[key]
                    self.request(url, "PATCH", update_payload)
                else:
                    print(f"{CC.OKBLUE} *{CC.ENDC} Netbox already up to date")
            else:
                ### Create
                print(f"{CC.OKGREEN} *{CC.ENDC} Create Device")
                create_response = self.request(url, "POST", payload)
                host_netbox_id = create_response.get('id')
                if not host_netbox_id:
                    logger.debug(payload)
                    logger.debug(create_response)
                    print(f"Cannot create Device: {create_response}")

            attr_name = f"{self.config['name']}_device_id"
            db_host.set_inventory_attribute(attr_name, host_netbox_id)

        print(f"\n{CC.OKGREEN} -- {CC.ENDC}Cleanup")
        for hostname, host_data in current_netbox_devices.items():
            if hostname not in found_hosts:
                print(f"{CC.OKBLUE} *{CC.ENDC} Delete {hostname}")
                device_id = host_data['id']
                self.request(f"{url}{device_id}", "DELETE", payload)
#.
#   .--- Import Hosts
    def import_hosts(self):
        """
        Import Objects from Netbox to the Syncer
        """

        for hostname, data in self.get_devices().items():
            labels = self.extract_data(data)
            if 'rewrite_hostname' in self.config and self.config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname, self.config['rewrite_hostname'], labels)
            host_obj = Host.get_host(hostname)
            print(f"\n{CC.HEADER}Process Device: {hostname}{CC.ENDC}")
            host_obj.update_host(labels)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
#.
