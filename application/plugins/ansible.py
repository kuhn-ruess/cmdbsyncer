
"""
Ansible Inventory Modul
"""
#pylint: disable=too-many-arguments, no-member
#   .-- Init
import json
import click

from mongoengine.errors import NotUniqueError
from mongoengine.errors import DoesNotExist

from application import app
from application.models.host import Host
from application.modules.debug import ColorCodes, attribute_table
from application.modules.rule.filter import Filter
from application.modules.rule.rewrite import Rewrite

from application.modules.ansible.models import AnsibleFilterRule, AnsibleRewriteAttributesRule, \
                                               AnsibleCustomVariablesRule
from application.modules.rule.models import CustomAttribute, FullCondition, FilterAction
from application.modules.ansible.rules import AnsibleVariableRule
from application.modules.ansible.syncer import SyncAnsible
from application.modules.ansible.site_syncer import SyncSites

@app.cli.group(name='ansible')
def cli_ansible():
    """Ansible related commands"""

#.
#   .-- Load Rules
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
#.
#   .-- Seed Default Rules
@cli_ansible.command('seed_cmk_default_rules')
def seed_default_rules():
    """
    Print matching rules and Inventory Outcome for Host
    """
    # pylint: disable=too-many-statements
    print("- Create Ansible Filters")
    rules = {
        'Default Variables': {
            'condition_typ': 'anyway',
            'outcomes': [
                 ('cmk_install_agent', 'whitelist_attribute'),
                 ('cmk_register_tls', 'whitelist_attribute'),
                 ('cmk_register_bakery', 'whitelist_attribute'),
                 ('cmk_discover', 'whitelist_attribute'),
                 ('cmk_linux_tmp', 'whitelist_attribute'),
                 ('cmk_windows_tmp', 'whitelist_attribute'),
                 ('cmk_agent_receiver_port', 'whitelist_attribute'),
                 ('cmk_main_server', 'whitelist_attribute'),
                 ('cmk_main_site', 'whitelist_attribute'),
                 ('cmk_site', 'whitelist_attribute'),
                 ('cmk_server', 'whitelist_attribute'),
            ],
            'conditions': [],
            'sort_field': 10,
        }
    }
    print("-- Done")

    for rule_name, settings in rules.items():
        rule = AnsibleFilterRule()
        rule.name = rule_name
        rule.condition_typ = settings['condition_typ']
        rule.sort_field = settings['sort_field']
        rule.enabled = True
        conditions = []
        for cond in settings['conditions']:
            if cond['type'] == 'label':
                condition = FullCondition()
                condition.match_type = 'tag'
                condition.tag_match = cond['tag'][0]
                condition.tag = cond['tag'][1]
                condition.value_match = cond['value'][0]
                condition.value = cond['value'][1]
                conditions.append(condition)
        rule.conditions = conditions
        outcomes = []
        for out in settings['outcomes']:
            attribute = FilterAction()
            attribute.attribute_name = out[0]
            attribute.action = out[1]
            outcomes.append(attribute)
        rule.outcomes = outcomes
        try:
            rule.save()
        except NotUniqueError:
            pass


    print("- Create Ansible Custom Variable Rules")
    rules = {
        'Default Ansible Variables': {
            'condition_typ': 'anyway',
            'outcomes': [
                ('ansible_user', ""),
            ],
            'conditions' : [],
            'sort_field': 10,

        },
        'Default Checkmk Variables' : {
            'condition_typ': 'anyway',
            'outcomes': [
                 ('cmk_main_server', ""),
                 ('cmk_main_site', ""),
                 ('cmk_user', ""),
                 ('cmk_password', "{{ACCOUNT:<NAME>:password}}"),
                 ('cmk_windows_tmp', ""),
                 ('cmk_linux_tmp', ""),
            ],
            'conditions': [],
            'sort_field': 11,
        },
        'Default Checkmk Install Agent Conditions' : {
            'condition_typ': 'any',
            'outcomes': [
                ('cmk_install_agent', 'true'),
                ('cmk_discover', 'true'),
                ('cmk_register_bakery', 'true'),
                ('cmk_register_tls', 'true'),
            ],
            'conditions': [
                {
                    'type': 'label',
                    'tag': ('equal', 'cmk_inventory_failed'),
                    'value': ('equal', 'True'),
                },
                {
                    'type': 'label',
                    'tag': ('equal', 'cmk_svc_check_mk_output'),
                    'value': ('equal', '[agent] Empty output'),
                },
                {
                    'type': 'label',
                    'tag': ('equal', 'cmk_svc_check_mk_output'),
                    'value': ('equal', '[agent] Communication failed'),
                },
                {
                    'type': 'label',
                    'tag': ('equal', 'cmk_svc_check_mk_agent_output'),
                    'value': ('equal', 'Version: 1'),
                },
            ],
            'sort_field': 12,

        },
    }



    for rule_name, settings in rules.items():
        rule = AnsibleCustomVariablesRule()
        rule.name = rule_name
        rule.condition_typ = settings['condition_typ']
        rule.enabled = False
        rule.sort_field = settings['sort_field']
        conditions = []
        for cond in settings['conditions']:
            if cond['type'] == 'label':
                condition = FullCondition()
                condition.match_type = 'tag'
                condition.tag_match = cond['tag'][0]
                condition.tag = cond['tag'][1]
                condition.value_match = cond['value'][0]
                condition.value = cond['value'][1]
                conditions.append(condition)
        rule.conditions = conditions
        outcomes = []
        for out in settings['outcomes']:
            attribute = CustomAttribute()
            attribute.attribute_name = out[0]
            attribute.attribute_value = out[1]
            outcomes.append(attribute)
        rule.outcomes = outcomes
        try:
            rule.save()
        except NotUniqueError:
            pass
    print("-- Done")

#.
#   .-- Debug Host
@cli_ansible.command('debug_host')
@click.argument("hostname")
def debug_ansible_rules(hostname):
    """
    Print matching rules and Inventory Outcome for Host
    """
    rules = load_rules()

    syncer = SyncAnsible()
    syncer.debug = True
    rules['filter'].debug = True
    syncer.filter = rules['filter']

    rules['rewrite'].debug = True
    syncer.rewrite = rules['rewrite']

    rules['actions'].debug=True
    syncer.actions = rules['actions']

    try:
        db_host = Host.objects.get(hostname=hostname)
    except DoesNotExist:
        print(f"{ColorCodes.FAIL}Host not Found{ColorCodes.ENDC}")
        return

    attributes = syncer.get_host_attributes(db_host)

    if not attributes:
        print(f"{ColorCodes.FAIL}THIS HOST IS IGNORED BY RULE{ColorCodes.ENDC}")
        return

    extra_attributes = syncer.get_host_data(db_host, attributes['all'])
    attribute_table("Full Attributes", attributes['all'])
    attributes['filtered'].update(extra_attributes)
    attribute_table("Final Attributes", attributes['filtered'])

#.
#   .-- Ansible Source
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
#.


#    .-- Checkmk Server Source
@cli_ansible.command('cmk-server-source')
@click.option("--list", is_flag=True)
@click.option("--host")
def source(list, host): #pylint: disable=redefined-builtin
    """Inventory Source for Checkmk Server Data"""
    #pylint: disable=no-else-return
    cmksitemngmt = SyncSites()
    if list:
        print(json.dumps(cmksitemngmt.get_full_inventory()))
        return True
    elif host:
        print(json.dumps(cmksitemngmt.get_host_inventory(host)))
        return True
    print("Params missing")
    return False

#.
