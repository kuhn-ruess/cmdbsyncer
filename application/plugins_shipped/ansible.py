
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
from application.helpers.get_ansible_action import GetAnsibleAction, GetAnsibleCustomVars
from application.helpers.get_label import GetLabel
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


@cli_ansible.command('debug_host')
@click.argument("host")
def debug_ansible_rules(host):
    """
    Print matching rules and Inventory Outcome for Host
    """
    action_helper = GetAnsibleAction(debug=True)
    custom_label_helper = GetAnsibleCustomVars(debug=True)
    label_helper = GetLabel()
    try:
        #pylint: disable=no-member
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
    custom_vars = custom_label_helper.get_action(db_host, inventory)
    inventory.update(custom_vars)

    print()
    print(f"{ColorCodes.HEADER} ***** Final Outcomes ***** {ColorCodes.ENDC}")
    print(f"{ColorCodes.UNDERLINE} Labels in DB {ColorCodes.ENDC}")
    pprint(db_host.get_labels())
    print(f"{ColorCodes.UNDERLINE}Labels after Filter {ColorCodes.ENDC}")
    pprint(labels)
    print(f"{ColorCodes.UNDERLINE}Outcomes based on Ansible Rules {ColorCodes.ENDC}")
    pprint(ansible_rules)
    print(f"{ColorCodes.UNDERLINE}Outcomes based on Custom Variables {ColorCodes.ENDC}")
    pprint(custom_vars)
    print(f"{ColorCodes.UNDERLINE}Complete Inventory Variables {ColorCodes.ENDC}")
    pprint(inventory)

def get_full_inventory():
    """
    Get information for ansible
    """
    action_helper = GetAnsibleAction()
    label_helper = GetLabel()
    custom_label_helper = GetAnsibleCustomVars()
    data = {
        '_meta': {
            'hostvars' : {}
        },
        'all': {
            'hosts' : []
        },
    }
    #pylint: disable=no-member
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
        custom_vars = custom_label_helper.get_action(db_host, inventory)
        inventory.update(custom_vars)
        data['_meta']['hostvars'][hostname] = inventory
        data['all']['hosts'].append(hostname)
    return data

def get_host_inventory(hostname):
    """
    Get Inventory for single host
    """
    action_helper = GetAnsibleAction()
    label_helper = GetLabel()
    try:
        #pylint: disable=no-member
        db_host = Host.objects.get(hostname=hostname)
    except DoesNotExist:
        return False
    labels, _ = label_helper.filter_labels(db_host.get_labels())
    ansible_rules = action_helper.get_action(db_host, labels)
    if ansible_rules.get('ignore'):
        return False
    inventory = db_host.get_inventory()
    if ansible_rules.get('vars'):
        inventory.update(ansible_rules['vars'])
    return inventory

@cli_ansible.command('source')
@click.option("--list", is_flag=True)
@click.option("--host")
def source(list, host): #pylint: disable=redefined-builtin
    """Inventory Source for Ansible"""
    #pylint: disable=no-else-return
    if list:
        print(json.dumps(get_full_inventory()))
        return True
    elif host:
        print(json.dumps(get_host_inventory(host)))
        return True
    print("Params missing")
    return False
