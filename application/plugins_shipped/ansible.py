
"""
Ansible Inventory Modul
"""
#pylint: disable=too-many-arguments
import datetime
import click
from application import app
from application.models.host import Host
from application.helpers.get_ansible_action import GetAnsibleAction
from application.helpers.get_label import GetLabel
import json


def get_rule_helper():
    """
    Return object with Rule Helper
    """
    helper = GetAnsibleAction()
    return helper


@app.cli.command('run_cmk2_inventory')
@click.argument('account')
def run_cmk2_inventory(account):
    """
    Run Inventory on checkmk to query information
    """

    action_helper = GetAnsibleAction()
    label_helper = GetLabel()

    for db_host in Host.objects():
        labels, _ = label_helper.filter_labels(db_host.get_labels())
        ansible_rules = action_helper.get_action(db_host, labels)
        print(f"{db_host.hostname}: {ansible_rules}")



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
