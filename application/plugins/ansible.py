
"""
Ansible Inventory Modul
"""
#pylint: disable=too-many-arguments, no-member
import json
from pprint import pprint
import click

from application import app
from application.models.host import Host
from application.modules.debug import ColorCodes
from application.modules.rule.filter import Filter
from application.modules.rule.rewrite import Rewrite

from application.modules.ansible.models import AnsibleFilterRule, AnsibleRewriteAttributesRule, \
                                               AnsibleCustomVariablesRule
from application.modules.ansible.rules import AnsibleVariableRule
from application.modules.ansible.syncer import SyncAnsible

def load_rules():
    """
    Cache all needed Rules for operation
    """
    attribute_filter = Filter()
    attribute_filter.rules = AnsibleFilterRule.objects(enabled=True).order_by('sort_field')

    attribute_rewrite = Rewrite()
    attribute_rewrite.rules = \
            AnsibleRewriteAttributesRule.objects(enabled=True).order_by('sort_field')

    ansible_rules = AnsibleVariableRule()
    ansible_rules.rules = AnsibleCustomVariablesRule.objects(enabled=True).order_by('sort_field')

    return {
        'filter': attribute_filter,
        'rewrite': attribute_rewrite,
        'actions': ansible_rules,
    }

@app.cli.group(name='ansible')
def cli_ansible():
    """Ansible related commands"""


@cli_ansible.command('debug_host')
@click.argument("hostname")
def debug_ansible_rules(hostname):
    """
    Print matching rules and Inventory Outcome for Host
    """
    print(f"{ColorCodes.HEADER} ***** Run Rules ***** {ColorCodes.ENDC}")

    rules = load_rules()

    syncer = SyncAnsible()
    syncer.debug = True
    rules['filter'].debug = True
    syncer.filter = rules['filter']

    rules['rewrite'].debug = True
    syncer.rewrite = rules['rewrite']

    rules['actions'].debug=True
    syncer.actions = rules['actions']

    db_host = Host.objects.get(hostname=hostname)

    attributes = syncer.get_host_attributes(db_host)

    if not attributes:
        print(f"{ColorCodes.FAIL}THIS HOST IS IGNORED BY RULE{ColorCodes.ENDC}")
        return

    extra_attributes = syncer.get_host_data(db_host, attributes['all'])

    print(f"{ColorCodes.HEADER} ***** Outcomes ***** {ColorCodes.ENDC}")
    print(f"{ColorCodes.UNDERLINE} Full Attributes List {ColorCodes.ENDC}")
    pprint(attributes['all'])
    print(f"{ColorCodes.UNDERLINE} Filtered Attributes List {ColorCodes.ENDC}")
    pprint(attributes['filtered'])
    print(f"{ColorCodes.UNDERLINE} Extra Attributes {ColorCodes.ENDC}")
    pprint(extra_attributes)

@cli_ansible.command('source')
@click.option("--list", is_flag=True)
@click.option("--host")
def source(list, host): #pylint: disable=redefined-builtin
    """Inventory Source for Ansible"""
    #pylint: disable=no-else-return
    rules = load_rules()
    syncer = SyncAnsible()
    syncer.filter = rules['filter']
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['actions']

    if list:
        print(json.dumps(syncer.get_full_inventory()))
        return True
    elif host:
        print(json.dumps(syncer.get_host_inventory(host)))
        return True
    print("Params missing")
    return False
