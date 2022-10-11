
"""
Cisco DNA Inventory
"""
#pylint: disable=too-many-arguments
import requests
from requests.auth import HTTPBasicAuth

import click
from application import app
from application.helpers.get_account import get_account_by_name
from application.models.host import Host
from application.helpers.debug import ColorCodes

@app.cli.group(name='cisco-dna')
def cli_cisco_dna():
    """Cisco DNA related commands"""

if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)

class CiscoDNA():
    """
    Cisco DNA
    """


    def __init__(self, config):
        """
        Init
        """
        self.address = config['address']
        self.user = config['username']
        self.password = config['password']
        self.account_id = str(config['_id'])
        self.account_name = config['name']
        self.verify = not app.config.get('DISABLE_SSL_ERRORS')

#   .-- get_auth_token
    def get_auth_token(self):
        """
        Return Auth Token
        """
        print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Get Auth Token")
        url = f"{self.address}/dna/system/api/v1/auth/token"
        response = requests.request(
             "POST",
              url,
              auth=HTTPBasicAuth(self.user, self.password),
              verify=self.verify,
              timeout=30,
        )
        if response.status_code < 400:
            response_json = response.json()
            return response_json['Token']
        print(response.text)
        raise Exception("Connection Problem")


#.
#   .-- Command: get_interfaces
    def get_interfaces(self):
        """
        Get Interfaces
        """
        inventory_attributes = [
            'id',
            'location',
            'platformId',
            'series',
        ]
        token = self.get_auth_token()
        print(f"\n{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Start Sync")
        url = f"{self.address}/dna/intent/api/v1/interface"
        headers = {"x-auth-token": token}
        #pylint: disable=missing-timeout
        response = requests.request("GET", url, headers=headers, verify=self.verify)
        response_json = response.json()['response']
        total = len(response_json)
        import pprint
        counter = 0
        for interface in response_json:
            counter += 1
            process = 100.0 * counter / total
            sync_id = interface['device_id']
            print(f"\n{ColorCodes.HEADER}({process:.0f}%) {sync_id}{ColorCodes.ENDC}")
            db_host = Host.objects.get(sync_id=sync_id)
            inventory = {}
            for attribute in inventory_attributes:
                inventory[f'cisco_dna_port_{attribute}'] = device[attribute]
            db_host.inventory.update_inventory('cisco_dna_port', inventory)
            db_host.sync_id = device['id']
            db_host.set_import_seen()
            db_host.set_account(self.account_id, self.account_name)
            db_host.save()

#.
#   .-- Command: get_hosts
    def get_hosts(self):
        """
        Get Host list
        """
        inventory_attributes = [
            'id',
            'location',
            'platformId',
            'series',
        ]
        token = self.get_auth_token()
        print(f"\n{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Start Sync")
        url = f"{self.address}/dna/intent/api/v1/network-device?hostname=.*"
        headers = {"x-auth-token": token}
        #pylint: disable=missing-timeout
        response = requests.request("GET", url, headers=headers, verify=self.verify)
        response_json = response.json()['response']
        total = len(response_json)
        counter = 0
        for device in response_json:
            counter += 1
            process = 100.0 * counter / total
            hostname = device['hostname']
            print(f"\n{ColorCodes.HEADER}({process:.0f}%) {hostname}{ColorCodes.ENDC}")
            db_host = Host.get_host(hostname)
            inventory = {}
            for attribute in inventory_attributes:
                inventory[f'cisco_dna_{attribute}'] = device[attribute]
            db_host.inventory.update_inventory('cisco_dna_', inventory)
            db_host.sync_id = device['id']
            db_host.set_import_seen()
            db_host.set_account(self.account_id, self.account_name)
            db_host.save()


#.
#   .-- CLI Commands
@cli_cisco_dna.command('get_hosts')
@click.argument('account')
def get_hosts(account):
    """Sync Switches from DNA"""
    try:
        if target_config := get_account_by_name(account):
            job = CiscoDNA(target_config)
            job.get_hosts()
        else:
            print(f"{ColorCodes.FAIL} Target not found {ColorCodes.ENDC}")
    except Exception as error_obj: #pylint: disable=broad-except
        print(f'C{ColorCodes.FAIL}Error: {error_obj} {ColorCodes.ENDC}')

@cli_cisco_dna.command('get_interfaces')
@click.argument('account')
def get_interfaces(account):
    """Sync Interfaces from DNA"""
    try:
        if target_config := get_account_by_name(account):
            job = CiscoDNA(target_config)
            job.get_interfaces()
        else:
            print(f"{ColorCodes.FAIL} Target not found {ColorCodes.ENDC}")
    except Exception as error_obj: #pylint: disable=broad-except
        print(f'C{ColorCodes.FAIL}Error: {error_obj} {ColorCodes.ENDC}')
