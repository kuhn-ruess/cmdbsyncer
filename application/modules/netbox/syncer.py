"""
Create Objects in Netbox
"""
#pylint: disable=no-member, too-many-locals, import-error
import requests

from application.models.host import Host
from application import app, log
from application.modules.debug import ColorCodes
from application.modules.plugin import Plugin

if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)


class SyncNetbox(Plugin):
    """
    Netbox Update/ Get Operations
    """

    def __init__(self):
        """
        Inital
        """
        self.log = log
        self.cache = {}
        self.interface_cache = {}
        self.verify = not app.config.get('DISABLE_SSL_ERRORS')

    def get_host_data(self, db_host, attributes):
        """
        Return commands for fullfilling of the netbox params
        """
        return self.actions.get_outcomes(db_host, attributes)

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

            response_json = response.json()
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
                        print(f"   {ColorCodes.OKGREEN}({process:.0f}%)...{counter}/{request_count}{ColorCodes.ENDC}")
                        sub_response= requests.get(next_page, headers=headers, verify=self.verify).json()
                        next_page = sub_response['next']
                        results += sub_response['results']
                return results
            return response_json
        except (ConnectionResetError, requests.exceptions.ProxyError):
            return {}


    def get_devices(self, syncer_only=False):
        """
        Read full list of devices
        """
        print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Netbox: "\
              f"Read all devices (Filter: {syncer_only})")
        url = 'dcim/devices/?limit=1000'
        if syncer_only:
            url += f"&cf_cmdbsyncer_id={self.config['_id']}"
        devices = self.request(url, "GET")
        return {x['display']:x for x in devices}


    def uppsert_element(self, key, value):
        """
        Returns the Element ID of given value
        directly or creates it first
        """

        endpoints = {
            'platform': {'url': 'dcim/platforms/',
                         'name_tag': 'name'},
            'device_type': {'url': 'dcim/device-types/',
                            'name_tag': 'model',
                            'additional_tags': ['manufacturer']},
            'device_role': {'url': 'dcim/device-roles/',
                            'name_tag': 'name'},
        }

        conf = endpoints[key]

        print(f"{ColorCodes.OKCYAN} *{ColorCodes.ENDC} Attribute: {key}:{value} will be synced")
        if not self.cache.get(key):
            print(f"{ColorCodes.OKGREEN}   -- {ColorCodes.ENDC}build cache for {key}")
            self.cache[key] = {}
            for entry in self.request(conf['url'], "GET"):
                self.cache[key][entry['display']] = entry['id']

        # FIND Data
        for entry_name, entry_id in self.cache[key].items():
            if entry_name == value:
                return entry_id

        # Create Entry
        payload = {
            conf['name_tag']: value,
            'slug': value.lower().replace(' ','_')
        }
        for extra_key in conf.get('additional_tags', []):
            payload[extra_key] = 1

        response = self.request(conf['url'], "POST", payload)
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} New {key} {value} created in Netbox")
        new_id = response['id']
        self.cache[key][value] = new_id
        return new_id


    def get_payload(self, db_host, custom_rules, inventory):
        """
        Build API Payload
        """
        payload = {
          "name": db_host.hostname,
          "device_type": 1,
          "device_role": 1,
          "tenant": 1,
          "platform": 1,
          "serial": "string",
          #"asset_tag": "string",
          "site": 1,
          "location": 1,
          "rack": 1,
          #"position": 0.5,
          #"face": "front",
          #"parent_device": {
          #  "name": "string"
          #},
          #"status": "offline",
          #"airflow": "front-to-rear",
          #"primary_ip4": 0,
          #"primary_ip6": 0,
          #"cluster": 0,
          #"virtual_chassis": 0,
          #"vc_position": 255,
          #"vc_priority": 255,
          #"comments": "string",
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


        key_translation = {
            'cisco_dna_serialNumber': "serial",
        }
        # Add custom variables who match to keyload
        for key in custom_rules:
            if key.startswith('nb_'):
                key = key[3:]
            if key in payload:
                payload[key] = custom_rules.get(key)
            if key.endswith("_sync"):
                # Sync attribute by value of given tag
                real_key = key[:-5]
                wanted = inventory.get(custom_rules.get(key), "Not defined")
                payload[real_key] = self.uppsert_element(real_key, wanted)

        # Add Inventory Variables we have a remap entry for
        for key in inventory:
            if key in key_translation:
                payload[key_translation[key]] = inventory[key]

        payload['custom_fields'] = {
            'cmdbsyncer_id': str(self.config['_id']),
        }

        return payload


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
                target_value = target_value['id']
            if target_value and str(value) != str(target_value):
                keys.append(key)
        return keys

    def update_interfaces(self, host_id, attributes):
        """
        Update Interfaces based on Attributes
        """
        url = '/dcim/interfaces'
        for entry in self.request(url, "GET"):
            print(entry)
        print(f"{ColorCodes.OKGREEN} *{ColorCodes.ENDC} Check Sync of Interfaces")

    def export_hosts(self):
        """
        Update Devices Table in Netbox
        """
        #pylint: disable=too-many-locals
        current_netbox_devices = self.get_devices(syncer_only=True)

        print(f"\n{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Start Sync")
        db_objects = Host.objects(available=True)
        total = len(db_objects)
        counter = 0
        found_hosts = []
        for db_host in db_objects:
            hostname = db_host.hostname
            counter += 1

            attributes = self.get_host_attributes(db_host)
            if not attributes:
                continue
            custom_rules = self.get_host_data(db_host, attributes['all'])

            attributes = attributes['filtered']

            process = 100.0 * counter / total
            print(f"\n{ColorCodes.HEADER}({process:.0f}%) {hostname}{ColorCodes.ENDC}")

            payload = self.get_payload(db_host, custom_rules, attributes)
            url = 'dcim/devices/'
            found_hosts.append(hostname)
            if hostname in current_netbox_devices:
                ## Update
                host_netbox_data = current_netbox_devices[hostname]
                host_netbox_id = host_netbox_data['id']
                if update_keys := self.need_update(host_netbox_data, payload):
                    print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Update Host")
                    url += f"{current_netbox_devices[hostname]['id']}/"
                    update_payload = {}
                    for key in update_keys:
                        update_payload[key] = payload[key]
                    self.request(url, "PATCH", update_payload)
                else:
                    print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Netbox already up to date")
            else:
                ### Create
                print(f"{ColorCodes.OKGREEN} *{ColorCodes.ENDC} Create Host")
                create_response = self.request(url, "POST", payload)
                host_netbox_id = create_response['id']
            if 'update_interfaces' in custom_rules:
                self.update_interfaces(host_netbox_id, attributes)

        print(f"\n{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Cleanup")
        for hostname, host_data in current_netbox_devices.items():
            if hostname not in found_hosts:
                print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Delete {hostname}")
                device_id = host_data['id']
                self.request(f"{url}{device_id}", "DELETE", payload)

    def import_hosts(self):
        """
        Import Hosts from Netbox to the Syncer
        """
        for device, _data in self.get_devices().items():
            host_obj = Host.get_host(device)
            print(f"\n{ColorCodes.HEADER}Process: {device}{ColorCodes.ENDC}")
            host_obj.set_import_seen()
            labels = {
            }
            host_obj.set_labels(labels)
            host_obj.save()
