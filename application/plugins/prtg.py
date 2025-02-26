"""
Import PRTG Data

API Output: 
{'devices': [{'device': 'myprtgserver',
              'device_raw': 'myprtgserver',
              'downsens': '',
              'downsens_raw': 0,
              'group': 'Local Probe',
              'group_raw': 'Local Probe',
              'host': '127.0.0.1',
              'host_raw': '127.0.0.1',
              'lastdown': '',
              'lastdown_raw': '',
              'lastup': '',
              'lastup_raw': '',
              'location': '<a '
                          'href="/devices.htm?filter_location=@sub(Wuppertal)">Wuppertal</a>',
              'location_raw': 'Wuppertal',
              'objid': 40,
              'objid_raw': 40,
              'priority': '5',
              'priority_raw': 5,
              'probe': 'Local Probe',
              'probe_raw': 'Local Probe',
              'status': 'OK',
              'status_raw': 3,
              'tags': 'corehealthsensor systemhealthsensor tests',
              'tags_raw': 'corehealthsensor systemhealthsensor tests',
              'totalsens': '6',
              'totalsens_raw': 6,
              'type': 'Device',
              'type_raw': 'device',
              'uptime': '',
              'uptime_raw': ''},
             {'device': 'DNS/Gateway: 192.168.215.2',
              'device_raw': 'DNS/Gateway: 192.168.215.2',
              'downsens': '',
              'downsens_raw': 0,
              'group': 'Netzwerk-Infrastruktur',
              'group_raw': 'Netzwerk-Infrastruktur',
              'host': '192.168.215.2',
              'host_raw': '192.168.215.2',
              'lastdown': '',
              'lastdown_raw': '',
              'lastup': '',
              'lastup_raw': '',
              'location': '<a '
                          'href="/devices.htm?filter_location=@sub(Wuppertal)">Wuppertal</a>',
              'location_raw': 'Wuppertal',
              'objid': 44,
              'objid_raw': 44,
              'priority': '3',
              'priority_raw': 3,
              'probe': 'Local Probe',
              'probe_raw': 'Local Probe',
              'status': 'OK',
              'status_raw': 3,
              'tags': '',
              'tags_raw': '',
              'totalsens': '1',
              'totalsens_raw': 1,
              'type': 'Device',
              'type_raw': 'device',
              'uptime': '',
              'uptime_raw': ''}
],
 'prtg-version': '25.1.102.1373',
 'treesize': 6}
"""
import click
from syncerapi.v1 import (
    register_cronjob,
    cc,
    Host,
)

from syncerapi.v1.core import (
   app,
   Plugin,
)

from syncerapi.v1.inventory import run_inventory

@app.cli.group(name='prtg')
def prtg_cli():
    """PRTG Commands"""

class Prtg(Plugin):
    """
    PRTG Import
    """

    def get_devices(self):
        """
        Return List of Devices with Attributes
        """
        url = f"{self.config['address']}/api/table.json"
        print(f"{cc.OKGREEN} -- {cc.ENDC}Request: Read all Hosts")

        prtg_attributes = [
           "objid", "device", "host", "group", "probe", "status", "priority",
           "uptime", "lastup", "lastdown", "location", "type",
           "tags"
        ]

        params = {
            "content": "devices",
            "output": "json",
            "columns": ",".join(prtg_attributes),
            "count": "5000",
            "username": self.config['username'],
            "password": self.config['password']
        }

        response = self.inner_request(method="GET", url=url, params=params)

        prtg_devices = response.json()
        if 'devices' not in prtg_devices:
            raise ValueError("No Data from PRTG, check your Account Settings")

        for device in prtg_devices['devices']:
            yield device['device'], device


    def import_objects(self):
        """
        Import Objects from PRTG
        """

        for hostname, device in self.get_devices():
            print(f" {cc.OKGREEN}** {cc.ENDC} Update {hostname}")
            host_obj = Host.get_host(hostname)

            if tags_string := device.get('tags_raw'):
                tags_list = tags_string.split()
                device['tags_raw'] = tags_list

            host_obj.update_host(device)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()

    def inventorize_objects(self):
        """
        Inventorize PRT Objects
        """
        self.connect()
        run_inventory(self.config, self.get_devices())

def import_prtg(account, debug=False):
    """
    Import
    """

    prtg = Prtg(account)
    prtg.debug = debug
    prtg.name = "PRTG: Import Objects"
    prtg.source = "prtg_import"

    prtg.import_objects()

@prtg_cli.command('import_devices')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_import_prtg(account, debug):
    """
    Import Objects from PRTG Monitoring
    """
    try:
        import_prtg(account, debug)
    except Exception as error:
        if debug:
            raise
        print(f"Error: {error}")

register_cronjob('PRTG Monitoring: Import Objects', import_prtg)

def inventorize_prtg(account, debug=False):
    """
    Inventorize
    """

    prtg = Prtg(account)
    prtg.debug = debug
    prtg.name = "PRTG: Inventorize Objects"
    prtg.source = "prtg_inventorzie"

    prtg.inventorize_objects()

@prtg_cli.command('inventorize_devices')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_inventorize_prtg(account, debug):
    """
    Inventorize Objects from PRTG Monitoring
    """
    try:
        inventorize_prtg(account, debug)
    except Exception as error:
        if debug:
            raise
        print(f"Error: {error}")

register_cronjob('PRTG Monitoring: Inventorize Objects', inventorize_prtg)
