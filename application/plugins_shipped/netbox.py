"""
Create Objects in Netbox
"""
#pylint: disable=no-member
from pprint import pprint
import click
import requests

from mongoengine.errors import DoesNotExist
from application.models.host import Host
from application import app, log
from application.helpers.debug import ColorCodes
from application.helpers.get_account import get_account_by_name
from application.helpers.get_netbox_actions import GetNetboxsRules
from application.helpers.get_label import GetLabel

@app.cli.group(name='netbox')
def cli_netbox():
    """Netbox Commands"""

if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)


class NetboxUpdate():
    """
    Netbox Update/ Get Operations
    """

    def __init__(self, config):
        """
        Inital
        """
        self.log = log
        self.config = config
        self.cache = {}
        self.verify = not app.config.get('DISABLE_SSL_ERRORS')
        self.rule_helper = GetNetboxsRules(debug=config.get('DEBUG'))
        self.label_helper = GetLabel()

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
                return response_json['results']
            return response_json
        except (ConnectionResetError, requests.exceptions.ProxyError):
            return {}


    def get_devices(self):
        """
        Read full list of devices
        """
        print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Netbox: Read all devices")
        url = 'dcim/devices/'
        return {x['display']:x for x in self.request(url, "GET")}


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

        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Need to sync {key} ({value})")
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
          #"custom_fields": {}
        }


        key_translation = {
            'cisco_dna_serialNumber': "serial",
        }
        # Add custom variables who match to keyload
        for key in custom_rules:
            if key in payload:
                payload[key] = custom_rules[key]
            if key.endswith("_sync"):
                # Sync attribute by value of given tag
                real_key = key[:-5]
                wanted = inventory[custom_rules[key]]
                payload[real_key] = self.uppsert_element(real_key, wanted)

        # Add Inventory Variables we have a remap entry for
        for key in inventory:
            if key in key_translation:
                payload[key_translation[key]] = inventory[key]

        return payload


    def need_update(self, target_payload, main_payload):
        """
        Compare Request Payload with Device Response
        """
        keys = []
        for key, value in main_payload.items():
            target_value = target_payload.get(key)
            if isinstance(target_value, dict):
                target_value = target_value['id']
            if target_value and str(value) != str(target_value):
                keys.append(key)
        return keys

    def export_hosts(self):
        """
        Update Devices Table in Netbox
        """
        current_devices = self.get_devices()

        print(f"\n{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Start Sync")
        db_objects = Host.objects(available=True)
        total = len(db_objects)
        counter = 0
        for db_host in db_objects:
            hostname = db_host.hostname
            counter += 1
            custom_rules, _labels, inventory = self.get_hostdata(db_host)
            if 'ignore_host' in custom_rules:
                continue
            process = 100.0 * counter / total
            print(f"\n{ColorCodes.HEADER}({process:.0f}%) {hostname}{ColorCodes.ENDC}")

            payload = self.get_payload(db_host, custom_rules, inventory)
            url = 'dcim/devices/'
            if hostname in current_devices:
                ## Update
                if update_keys := self.need_update(current_devices[hostname], payload):
                    print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Update Host")
                    url += f"{current_devices[hostname]['id']}/"
                    update_payload = {}
                    for key in update_keys:
                        update_payload[key] = payload[key]
                    self.request(url, "PATCH", update_payload)
                else:
                    print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Nothing to do")
            else:
                ### Create
                print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Create Host")
                self.request(url, "POST", payload)


    def get_hostdata(self, db_host):
        """
        Process all Rules and return final outcome
        """
        labels, _ = self.label_helper.filter_labels(db_host.get_labels())
        inventory = db_host.get_inventory()
        merged = {}
        merged.update(labels)
        merged.update(inventory)
        custom_rules = self.rule_helper.get_action(db_host, merged)

        return custom_rules, labels, inventory

    def debug_rules(self, hostname):
        """
        Debug Netbox Rules for Object
        """
        try:
            #pylint: disable=no-member
            db_host = Host.objects.get(hostname=hostname)
        except DoesNotExist:
            print("Host not found")
            return
        if not db_host.available:
            print("Host not  marked as available")
            return

        custom_rules, labels, inventory = self.get_hostdata(db_host)

        print()
        print(f"{ColorCodes.HEADER} ***** Final Outcomes ***** {ColorCodes.ENDC}")
        print(f"{ColorCodes.UNDERLINE}Custom Rules{ColorCodes.ENDC}")
        pprint(custom_rules)
        if custom_rules.get('ignore_host'):
            print("!! This System would be ignored")
        print(f"{ColorCodes.UNDERLINE}Original Labels{ColorCodes.ENDC}")
        pprint(labels)
        print(f"{ColorCodes.UNDERLINE}Filtered and renamed Inventory Variables{ColorCodes.ENDC}")
        pprint(inventory)
        print(f"{ColorCodes.UNDERLINE}Final Outcome{ColorCodes.ENDC}")

#   .-- Command: Export Hosts
@cli_netbox.command('export_hosts')
@click.argument("account")
def netebox_host_export(account):
    """Move Objects into Netbox"""
    try:
        target_config = get_account_by_name(account)
        if target_config:
            job = NetboxUpdate(target_config)
            job.export_hosts()
        else:
            print(f"{ColorCodes.FAIL} Target not found {ColorCodes.ENDC}")
    except Exception as error_obj:
        raise
        print(f'C{ColorCodes.FAIL}Connection Error: {error_obj} {ColorCodes.ENDC}')
#.
#   .-- Command: Debug Hosts
@cli_netbox.command('debug_host')
@click.argument("hostname")
def netebox_host_debug(hostname):
    """Debug Host Rules"""
    try:
        job = NetboxUpdate({'DEBUG': True})
        job.debug_rules(hostname)
    except Exception as error_obj:
        raise
#.
