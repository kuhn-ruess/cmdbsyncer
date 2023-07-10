"""
Create Objects in Netbox
"""
#pylint: disable=no-member, too-many-locals, import-error
import requests

from application.models.host import Host
from application import app, log
from application.modules.debug import ColorCodes as CC
from application.modules.plugin import Plugin

if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)


class SyncNetbox(Plugin):
    """
    Netbox Update/ Get Operations
    """
#   .-- Init
    def __init__(self, debug):
        """
        Inital
        """
        self.log = log
        self.print_debug = debug
        self.cache = {}
        self.interface_cache = {}
        self.verify = not app.config.get('DISABLE_SSL_ERRORS')
#.
#   .-- Get Host Data
    def get_host_data(self, db_host, attributes):
        """
        Return commands for fullfilling of the netbox params
        """
        return self.actions.get_outcomes(db_host, attributes)
#.
#   . -- Request
    def request(self, path, method='GET', data=None, additional_header=None):
        """
        Handle Request to Netbox
        """
        address = self.config['address']
        password = self.config['password']
        url = f'{address}/api/{path}'
        headers = {
            'Authorization': f"Token {password}",
            'Content-Type': 'application/json',
        }
        if additional_header:
            headers.update(additional_header)
        try:
            method = method.lower()
            #pylint: disable=missing-timeout
            if method == 'get':
                response = requests.get(url,
                                        headers=headers,
                                        params=data,
                                        verify=self.verify,
                                       )
            elif method == 'post':
                response = requests.post(url, json=data, headers=headers, verify=self.verify)
            elif method == 'patch':
                response = requests.patch(url, json=data, headers=headers, verify=self.verify)
            elif method == 'put':
                response = requests.put(url, json=data, headers=headers, verify=self.verify)
            elif method == 'delete':
                response = requests.delete(url, headers=headers, verify=self.verify)
                # Checkmk gives no json response here, so we directly return
                return True, response.headers
            if response.status_code >= 299:
                print(f"Error: {response.text}")
            try:
                response_json = response.json()
            except:
                print(response.text)
                raise
            if 'results' in response_json:
                results = []
                results += response_json['results']
                if response_json['next']:
                    total = response_json['count']
                    request_count = int(round(total/len(response_json['results']),0)) + 1
                    print(f" -- Require {request_count} requests. {total} objects in total")
                    counter = 0
                    next_page = response_json['next']
                    while next_page:
                        counter += 1
                        process = 100.0 * counter / request_count
                        # pylint: disable=line-too-long
                        print(f"   {CC.OKGREEN}({process:.0f}%)...{counter}/{request_count}{CC.ENDC}")
                        sub_response= requests.get(next_page, headers=headers, verify=self.verify).json()
                        next_page = sub_response['next']
                        results += sub_response['results']
                return results
            return response_json
        except (ConnectionResetError, requests.exceptions.ProxyError):
            return {}
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
#   .-- Get VMS
    def get_vms(self, syncer_only=False):
        """
        Read full list of vms
        """
        print(f"{CC.OKGREEN} -- {CC.ENDC}Netbox: "\
              f"Read all VMs (Filter only CMDB Syncer: {syncer_only})")
        url = 'virtualisation/vitual-machines/?limit=10000'
        if syncer_only:
            url += f"&cf_cmdbsyncer_id={self.config['_id']}"
        vms = self.request(url, "GET")
        return {x['display']:x for x in vms}
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
            'device_role': {'url': 'dcim/device-roles/',
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
          "device_role": 1,
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
                payload[key] = custom_rules.get(key)

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
#   .-- Get Interface Payload
    def get_interface_payload(self, host_id, if_attributes):
        """ Return Interface Payload
        """
        status_map = {
            'up' : True,
        }

        # @Todo: Detect Type:
        interface_type = "other"
        if if_attributes['interfaceType'] == "Virtual":
            interface_type = 'virtual'


        duplex_modes = {
            'FullDuplex' : 'full',
            'HalfDuplex' : 'half',
        }
        duplex_mode = duplex_modes.get(if_attributes.get('duplex'), 'auto')

        access_modes = {
            'access': 'access',
            'trunk': 'tagged',
        }
        access_mode = access_modes.get(if_attributes.get('portMode'))

        interface_speed = int(if_attributes.get('speed',0))

        payload = {
          "device": host_id,
          #"module": 0,
          "name": if_attributes['portName'],
          #"label": "string",
          "type": interface_type,
          "enabled": status_map.get(if_attributes['adminStatus'].lower(), False),
          #"parent": 0,
          #"bridge": 0,
          #"lag": 0,
          "speed": interface_speed,
          "duplex": duplex_mode,
          #"wwn": "string",
          #"mgmt_only": true,
          "description": if_attributes.get('description'),
          #"rf_role": "ap",
          #"rf_channel": "2.4g-1-2412-22",
          #"poe_mode": "pd",
          #"poe_type": "type1-ieee802.3af",
          #"rf_channel_frequency": 0,
          #"rf_channel_width": 0,
          #"tx_power": 127,
          #"untagged_vlan": 0,
          #"tagged_vlans": [
          #  0
          #],
          #"mark_connected": true,
          #"cable": {
          #  "label": "string"
          #},
          #"wireless_link": 0,
          #"wireless_lans": [
          #  0
          #],
          #"vrf": 0,
          #"tags": [
          #  {
          #    "name": "string",
          #    "slug": "string",
          #    "color": "string"
          #  }
          #],
          #"custom_fields": {}
        }
        if if_attributes['macAddress']:
            payload['mac_address'] = if_attributes['macAddress'].upper()
        if access_mode:
            payload["mode"] =  access_mode
        if mtu := if_attributes.get('mtu'):
            payload["mtu"] = int(mtu)
        if self.print_debug:
            print(payload)
        return payload
#.
#   .-- Create Interface
    def create_interface(self, host_id, payload):
        """
        Create Interface in Netbox
        """

#.
#   .-- build interface_list
    def get_interface_list_by_attributes(self, attributes):
        """
        Return List of Interfaces
        """
        interfaces = {}
        for attribute, value in attributes.items():
            # @TODO: Build more general approach
            # Better RegEx Rewrites needed for that
            if attribute.startswith('cisco_dnainterface'):
                splitted = attribute.split('_')
                interface_id = splitted[-2]
                field_name = splitted[-1]
                interfaces.setdefault(interface_id, {})
                interfaces[interface_id][field_name] = value
        return interfaces


#.
#   .-- Update Interfaces
    def update_interfaces(self, host_id, attributes):
        """
        Update Interfaces based on Attributes
        """
        url = f'dcim/interfaces?device_id={host_id}'
        device_interfaces = {}
        for entry in self.request(url, "GET"):
            # We need some rewrite here to match the payloads of the api
            del entry['device']
            entry['name'] = entry['display']
            device_interfaces[entry['name']] = entry

        url = 'dcim/interfaces/'
        interfaces = self.get_interface_list_by_attributes(attributes)
        for _interface, interface_data in interfaces.items():
            payload = self.get_interface_payload(host_id, interface_data)
            port_name = interface_data['portName']
            if port_name not in device_interfaces:
                print(f"{CC.OKBLUE} *{CC.ENDC} Create Interface {port_name}")
                create_response = self.request(url, "POST", payload)
                if self.print_debug:
                    print(f"Debug: Created Interface: {create_response}")
            elif update_keys := self.need_update(device_interfaces[port_name], payload):
                update_payload = {}
                for key in update_keys:
                    update_payload[key] = payload[key]
                print(f"{CC.OKGREEN} *{CC.ENDC} Update Interface {port_name} ({update_keys})")
                url = f'dcim/interfaces/{device_interfaces[port_name]["id"]}/'
                self.request(url, "PATCH", update_payload)

        print(f"{CC.OKGREEN} *{CC.ENDC} Check Sync of Interfaces")
#.
#   .--- Export Hosts
    def export_hosts(self):
        """
        Update Devices Table in Netbox
        """
        #pylint: disable=too-many-locals
        current_netbox_devices = self.get_devices(syncer_only=True)

        print(f"\n{CC.OKGREEN} -- {CC.ENDC}Start Sync")
        db_objects = Host.objects(available=True)
        total = len(db_objects)
        counter = 0
        found_hosts = []
        for db_host in db_objects:
            hostname = db_host.hostname
            counter += 1

            all_attributes = self.get_host_attributes(db_host, 'netbox')
            if not all_attributes:
                continue
            custom_rules = self.get_host_data(db_host, all_attributes['all'])

            process = 100.0 * counter / total
            print(f"\n{CC.HEADER}({process:.0f}%) {hostname}{CC.ENDC}")

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
                print(f"{CC.OKGREEN} *{CC.ENDC} Create Host")
                create_response = self.request(url, "POST", payload)
                host_netbox_id = create_response.get('id')
                if not host_netbox_id:
                    print(payload)
                    print(create_response)
                    raise Exception("Cannot create Host")
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
        for device, _data in self.get_devices().items():
            host_obj = Host.get_host(device)
            print(f"\n{CC.HEADER}Process Device: {device}{CC.ENDC}")
            labels = {
            }
            host_obj.update_host(labels)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()

        for device, _data in self.get_vms().items():
            host_obj = Host.get_host(device)
            print(f"\n{CC.HEADER}Process VM: {device}{CC.ENDC}")
            labels = {
            }
            host_obj.update_host(labels)
            do_save = host_obj.update_host(labels)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
#.
