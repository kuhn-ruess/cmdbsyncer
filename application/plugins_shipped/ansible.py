
"""
Ansible Inventory Modul
"""
#pylint: disable=too-many-arguments
import json
from pprint import pprint
import click
from mongoengine.errors import DoesNotExist

from application import app
from application.models.host import Host
from application.modules.cmk2 import CMK2
from application.helpers.get_ansible_action import GetAnsibleAction
from application.helpers.get_label import GetLabel
from application.helpers.get_account import get_account_by_name
from application.helpers.debug import ColorCodes

@app.cli.group(name='ansible')
def cli_ansible():
    """Ansible related commands"""

def get_rule_helper():
    """
    Return object with Rule Helper
    """
    helper = GetAnsibleAction()
    return helper


@cli_ansible.command('cmk_hosts_inventory')
@click.argument('account')
def run_cmk2_inventory(account):
    """
    Query CMK with Version  2.1p9 for Inventory Data
    """
    inventory_target = [
        'site', 'inventory_failed','is_offline','tag_agent',
    ]
    config = get_account_by_name(account)
    cmk = CMK2(config)

    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{account}{ColorCodes.ENDC}")


    url = "domain-types/host_config/collections/all?effective_attributes=true"
    api_hosts = cmk.request(url, method="GET")
    for host in api_hosts[0]['value']:
        hostname = host['id']
        attributes = host['extensions']['effective_attributes']
        host_inventory = {}
        for attribute in attributes:
            if attribute in inventory_target:
                host_inventory[f"cmk_{attribute}"] = attributes[attribute]

        db_host = Host.get_host(hostname, False)
        if db_host:
            db_host.inventory = host_inventory
            db_host.save()
            print(f" {ColorCodes.OKGREEN}* {ColorCodes.ENDC} Updated {hostname}")
        else:
            print(f" {ColorCodes.FAIL}* {ColorCodes.ENDC} Hot in Syncer: {hostname}")



@cli_ansible.command('debug_host')
@click.argument("host")
def debug_ansible_rules(host):
    """
    Print matching rules and Inventory Outcome for Host
    """
    action_helper = GetAnsibleAction(debug=True)
    label_helper = GetLabel()
    try:
        db_host = Host.objects.get(hostname=host)
    except DoesNotExist:
        print("Host not found")
        return
    labels, _ = label_helper.filter_labels(db_host.get_labels())
    ansible_rules = action_helper.get_action(db_host, labels)
    inventory = {}
    if ansible_rules.get('vars'):
        inventory = ansible_rules['vars']
    inventory.update(db_host.get_inventory())

    print()
    print(f"{ColorCodes.HEADER} ***** Final Outcomes ***** {ColorCodes.ENDC}")
    print(f"{ColorCodes.UNDERLINE} Labels in DB {ColorCodes.ENDC}")
    pprint(db_host.get_labels())
    print(f"{ColorCodes.UNDERLINE}Labels after Filter {ColorCodes.ENDC}")
    pprint(labels)
    print(f"{ColorCodes.UNDERLINE}Outcomes based on Ansible Rules {ColorCodes.ENDC}")
    pprint(ansible_rules)
    print(f"{ColorCodes.UNDERLINE}Complete Inventory Variables {ColorCodes.ENDC}")
    pprint(inventory)



@cli_ansible.command('source')
@click.option("--list", is_flag=True)
@click.option("--host")
def maintenance(list, host): #pylint: disable=redefined-builtin
    """Inventory Source for Ansible"""
    action_helper = GetAnsibleAction()
    label_helper = GetLabel()
    #pylint: disable=no-else-return
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
            labels, _ = label_helper.filter_labels(db_host.get_labels())
            ansible_rules = action_helper.get_action(db_host, labels)
            if ansible_rules.get('ignore'):
                continue
            inventory = {}
            if ansible_rules.get('vars'):
                inventory = ansible_rules['vars']
            inventory.update(db_host.get_inventory())
            data['_meta']['hostvars'][hostname] = inventory
            data['all']['hosts'].append(hostname)
        print(json.dumps(data))
        return True

    elif host:
        try:
            db_host = Host.objects.get(hostname=host)
        except DoesNotExist:
            return False
        labels, _ = label_helper.filter_labels(db_host.get_labels())
        ansible_rules = action_helper.get_action(db_host, labels)
        if ansible_rules.get('ignore'):
            return False
        inventory = db_host.get_inventory()
        if ansible_rules.get('vars'):
            inventory.update(ansible_rules['vars'])
        print(json.dumps(inventory))
        return True
    print("Params missing")
    return False
