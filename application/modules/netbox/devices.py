"""
Create Devices in Netbox
"""
#pylint: disable=no-member, too-many-locals, import-error

from application.modules.netbox.netbox import SyncNetbox

from application.models.host import Host
from application import app, log, logger
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

#   .-- Get Host Data
    def get_host_data(self, db_host, attributes):
        """
        Return commands for fullfilling of the netbox params
        """
        return self.actions.get_outcomes(db_host, attributes)
#.
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
    def create_sub_entry(self, endpoint, value, inventory):
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
            'primary_ip4': {'url': 'ipam/ip-addresses/',
                            'name_tag': 'address',
                            'fallback': None,
                            'split_needle': "/",
                           },
            'primary_ip6': {'url': 'ipam/ip-addresses/',
                            'name_tag': 'address',
                            'fallback': None,
                           },
        }

        conf = endpoints[endpoint]
        if not value:
            fallback = conf['fallback']
            print(f"{CC.FAIL} *{CC.ENDC} {endpoint} invalid Value: {value}, Fallback to {fallback}")
            if not fallback:
                return None
            value = fallback
        value = value.lower()



        print(f"{CC.OKCYAN} *{CC.ENDC} Attribute: {endpoint}:{value} will be synced")
        if not self.cache.get(endpoint):
            print(f"{CC.OKGREEN} ** {CC.ENDC}build cache for {endpoint}")
            self.cache[endpoint] = {}
            for entry in self.request(conf['url'], "GET"):
                self.cache[endpoint][entry['display'].lower()] = entry['id']

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
        for extra_key in conf.get('sub_entries', []):
            payload[extra_key] = self.create_sub_entry(extra_key, \
                            inventory.get('manufacturer', 'Manufacturer Attribute Missing'), None)

        response = self.request(conf['url'], "POST", payload)
        print(f"{CC.OKBLUE} *{CC.ENDC} New {endpoint} {value} created in Netbox")
        new_id = response.get('id')
        if not new_id:
            print(response)
            raise ValueError(f"Invalid Response from Netbox for {value}")
        self.cache[endpoint][value] = new_id
        return new_id
#.
#   .-- Get Device Payload
    def get_payload(self, db_host, custom_rules, inventory):
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


        keys_from_inventory = [
            "serial",
        ]
        # Add custom variables who match to keyload
        for key in custom_rules:
            if key.endswith("_sync"):
                # Sync attribute by value of given tag
                # Needs to be first since we need nb_ in keyname
                endpoint_name = key[3:-5]
                needed_entry = inventory.get(custom_rules.get(key))
                payload[endpoint_name] = self.create_sub_entry(endpoint_name,
                                                                needed_entry, inventory)


            if key.startswith('nb_'):
                key = key[3:]
            if key in payload:
                payload[key] = custom_rules.get("nb_"+key)

        # Add Inventory Variables we have a remap entry for
        for key in inventory:
            if key in keys_from_inventory:
                payload[key]= inventory.get(key)

        keys = list(payload.keys())
        for key in keys:
            if not payload[key]:
                del payload[key]

        payload['custom_fields'] = {
            'cmdbsyncer_id': str(self.config['_id']),
        }
        logger.debug(f"Payload: {payload}")
        return payload
#.
#   .-- Device Need Update?
    def need_update(self, target_payload, main_payload):
        """
        Compare Request Payload with Device Response
        """
        keys = []
        for key, value in main_payload.items():
            target_value = target_payload.get(key)
            if isinstance(target_value, dict):
                if 'cmdbsyncer_id' in target_value:
                    continue
                target_value = target_value.get('id')
            if target_value and str(value) != str(target_value):
                keys.append(key)
        return keys
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

            payload = self.get_payload(db_host, custom_rules, all_attributes['all'])
            url = 'dcim/devices/'
            found_hosts.append(hostname)
            if hostname in current_netbox_devices:
                ## Update
                host_netbox_data = current_netbox_devices[hostname]
                host_netbox_id = host_netbox_data['id']
                if update_keys := self.need_update(host_netbox_data, payload):
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
            if 'update_interfaces' in custom_rules:
                self.update_interfaces(host_netbox_id, all_attributes['all'])

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

        def extract_data(data):
            """
            Extract Netbox fields
            """
            labels = {}
            for key, value in data.items():
                if key == 'custom_fields':
                    if 'cmdbsyncer_id' in value:
                        del value['cmdbsyncer_id']
                    labels.update(value)
                elif isinstance(value, str):
                    labels[key] = value
                elif isinstance(value, dict):
                    if 'display' in value:
                        labels[key] = value['display']
                    elif 'label' in value:
                        labels[key] = value['label']
            return labels

        for hostname, data in self.get_devices().items():
            labels = extract_data(data)
            if 'rewrite_hostname' in self.config and self.config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname, self.config['rewrite_hostname'], labels)
            host_obj = Host.get_host(hostname)
            print(f"\n{CC.HEADER}Process Device: {hostname}{CC.ENDC}")
            host_obj.update_host(labels)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
#.
