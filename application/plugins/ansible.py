"""
Ansible Inventory Modul
"""
#pylint: disable=too-many-arguments, no-member
import json
import click

from mongoengine.errors import DoesNotExist

from application import app
from application.models.host import Host
from application.modules.debug import ColorCodes, attribute_table
from application.modules.rule.filter import Filter
from application.modules.rule.rewrite import Rewrite

from application.modules.ansible.models import AnsibleFilterRule, AnsibleRewriteAttributesRule, \
                                               AnsibleCustomVariablesRule
from application.modules.ansible.rules import AnsibleVariableRule
from application.modules.ansible.syncer import SyncAnsible
from application.modules.ansible.site_syncer import SyncSites
from application.helpers.cron import register_cronjob

@app.cli.group(name='ansible')
def cli_ansible():
    """Ansible related commands"""

#   .-- Load Rules
def load_rules():
    """
    Cache all needed Rules for operation
    """
    attribute_filter = Filter()
    attribute_filter.cache_name = 'ansible_filter'
    attribute_filter.rules = AnsibleFilterRule.objects(enabled=True).order_by('sort_field')

    attribute_rewrite = Rewrite()
    attribute_rewrite.cache_name = 'ansible_rewrite'
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
        if 'ansible' in db_host.cache:
            del db_host.cache['ansible']
        db_host.save()
    except DoesNotExist:
        print(f"{ColorCodes.FAIL}Host not Found{ColorCodes.ENDC}")
        return

    attributes = syncer.get_host_attributes(db_host, 'ansible')

    if not attributes:
        print(f"{ColorCodes.FAIL}THIS HOST IS IGNORED BY RULE{ColorCodes.ENDC}")
        return

    extra_attributes = syncer.get_host_data(db_host, attributes['all'])
    attribute_table("Full Attributes", attributes['all'])
    attributes['filtered'].update(extra_attributes)
    attribute_table("Final Attributes", attributes['filtered'])

#.
#   .-- Ansible Cache

def _inner_udpate_cache():
    """
    Update Cache of Ansible
    """
    print(f"{ColorCodes.OKGREEN}Delete current Cache{ColorCodes.ENDC}")
    for host in Host.get_export_hosts():
        if 'ansible' in host.cache:
            del host.cache['ansible']
            host.save()
    print(f"{ColorCodes.OKGREEN}Build new Cache{ColorCodes.ENDC}")
    rules = load_rules()
    syncer = SyncAnsible()
    syncer.filter = rules['filter']
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['actions']
    # Do the action which triggers the caches
    syncer.get_full_inventory()

@cli_ansible.command('update_cache')
def update_cache():
    """
    Update Cache for Ansible
    """
    _inner_udpate_cache()

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
#   .-- Checkmk Server Source
@cli_ansible.command('cmk-server-source')
@click.option("--list", is_flag=True)
@click.option("--host")
def server_source(list, host): #pylint: disable=redefined-builtin
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
#   . -- Ansible Playbook

#def print_out(data, runner_config):
#    """
#    Debug print
#    """
#    print(data, runner_config)
#
#def run_agent_playbook():
#    """
#    Run Ansible Playbook
#    """
#
#    rules = load_rules()
#    syncer = SyncAnsible()
#    syncer.filter = rules['filter']
#    syncer.rewrite = rules['rewrite']
#    syncer.actions = rules['actions']
#
#    inventory = syncer.get_full_inventory()
#    playbook = './ansible/cmk_agent_mngmt.yml'
#
#    path = os.path.abspath(os.getcwd())
#    path += "/ansible"
#    envvars = {
#        'PATH': path,
#        'ANSIBLE_ROLES_PATH': path,
#    }
#    result = ansible_runner.run(playbook=playbook,
#                                status_handler=print_out,
#                                envvars = envvars,
#                                inventory=inventory)
#    print(result)
#
#@cli_ansible.command('run_agent_playbook')
#def cli_run_agent_playbook():
#    """
#    Run Ansible Playbook
#    """
#    run_agent_playbook()
#
#.
register_cronjob('Ansible: Build Cache', _inner_udpate_cache)
