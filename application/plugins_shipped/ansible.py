
"""
Ansible Inventory Modul
"""
#pylint: disable=too-many-arguments
import datetime
import click
from application import app
from application.models.host import Host
import json



@app.cli.command('ansible')
@click.option("--list", is_flag=True)
@click.option("--host")
def maintenance(list, host):
    """Return JSON Inventory Data for Ansible"""
    if list:
        data = {
            '_meta': {
                'hostvars' : {}
            },
            'all': {
                'hosts' : []
            },
        }
        for db_host in Host.objects():
            hostname = db_host.hostname
            data['_meta']['hostvars'][hostname] = db_host.get_inventory()
            data['all']['hosts'].append(hostname)
        print(json.dumps(data))


    else:
        db_host = Host.objects.get(hostname=host)
        print(json.dumps(db_host.get_inventory()))
