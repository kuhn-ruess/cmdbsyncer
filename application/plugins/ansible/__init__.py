"""
Ansible Inventory Modul
"""
import json
import click

from mongoengine.errors import DoesNotExist

from rich.console import Console
from rich.table import Table

from application import app
from application.models.host import Host
from application.modules.debug import ColorCodes, attribute_table
from application.modules.rule.filter import Filter
from application.modules.rule.rewrite import Rewrite

from .models import AnsibleFilterRule, AnsibleRewriteAttributesRule, \
                    AnsibleCustomVariablesRule
from .rules import AnsibleVariableRule
from .inventory import AnsibleInventory
from .site_syncer import SyncSites

from application.helpers.cron import register_cronjob

@app.cli.group(name='ansible')
def cli_ansible():
    """Ansible Datasource and Debug"""

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

    syncer = AnsibleInventory()
    syncer.debug = True
    rules['filter'].debug = True
    syncer.filter = rules['filter']

    rules['rewrite'].debug = True
    syncer.rewrite = rules['rewrite']

    rules['actions'].debug=True
    syncer.actions = rules['actions']

    try:
        db_host = Host.objects.get(hostname=hostname)
        for key in list(db_host.cache.keys()):
            if key.lower().startswith('ansible'):
                del db_host.cache[key]
        if 'CustomAttributeRule' in db_host.cache:
            del db_host.cache['CustomAttributeRule']
        db_host.save()
    except DoesNotExist:
        print(f"{ColorCodes.FAIL}Host not Found{ColorCodes.ENDC}")
        return

    attributes = syncer.get_attributes(db_host, 'ansible')

    if not attributes:
        print(f"{ColorCodes.FAIL}THIS HOST IS IGNORED BY RULE{ColorCodes.ENDC}")
        return


    hidden_fields = ['ansible_password', 'ansible_ssh_pass']

    extra_attributes = syncer.get_host_data(db_host, attributes['all'])
    for attr in list(extra_attributes.keys()):
        if attr in hidden_fields:
            extra_attributes[attr] = "HIDDEN..."+ extra_attributes[attr][-3:]
    attribute_table("Full Attributes", attributes['all'])
    attributes['filtered'].update(extra_attributes)
    attribute_table("Final Attributes", attributes['filtered'])

#.
#   .-- Ansible Cache

def _inner_update_cache(account=False):
    """
    Update Cache of Ansible
    """
    # pyint: disable=unused-argument
    # Account Variable needed because of cronjobs 
    print(f"{ColorCodes.OKGREEN}Delete current Cache{ColorCodes.ENDC}")
    Host.objects.filter(cache__ansible__exists=True).update(unset__cache__ansible=1)
    print(f"{ColorCodes.OKGREEN}Build new Cache{ColorCodes.ENDC}")
    rules = load_rules()
    syncer = AnsibleInventory()
    syncer.name = "Rebuild Ansible Cache"
    syncer.filter = rules['filter']
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['actions']
    # Do the action which triggers the caches
    syncer.get_full_inventory(show_status=True)

@cli_ansible.command('update_cache')
def update_cache():
    """
    Update Cache for Ansible
    """
    _inner_update_cache()

#.
#   .-- Ansible Source
@cli_ansible.command('source')
@click.option("--list", is_flag=True)
@click.option("--host")
def source(list, host):
    """Inventory Source for Ansible"""
    rules = load_rules()
    syncer = AnsibleInventory()
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
def server_source(list, host):
    """Inventory Source for Checkmk Server Data"""
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
#   .-- Debug Filter
@cli_ansible.command('debug_filter')
@click.option('--list-rules', '-l', is_flag=True, help='List all available filter rules')
@click.option('--filter-name', '-f', default=None, help='Name of specific filter rule to test')
@click.option('--show-matched', '-m', is_flag=True, help='Show hosts matched by filter (will be processed)')
@click.option('--show-ignored', '-i', is_flag=True, help='Show hosts NOT matched (ignored by filter)')
def debug_filter(list_rules, filter_name, show_matched, show_ignored):
    """
    Debug filter rules against all hosts.

    Examples:
        ansible debug_filter -l
        ansible debug_filter -m -i
        ansible debug_filter -f "MyRule" -m
        ansible debug_filter -f "MyRule" -i
    """
    console = Console()

    if list_rules:
        rules = AnsibleFilterRule.objects()
        table = Table(title="Ansible Filter Rules")
        table.add_column("Name", style="cyan")
        table.add_column("Enabled", style="green")
        table.add_column("Condition Type", style="yellow")
        table.add_column("Sort", style="magenta")
        table.add_column("Conditions", style="blue")

        for rule in rules:
            table.add_row(
                rule.name,
                "Yes" if rule.enabled else "No",
                rule.condition_typ,
                str(rule.sort_field),
                str(len(rule.conditions))
            )
        console.print(table)
        return

    with app.app_context():
        if filter_name:
            rules = AnsibleFilterRule.objects(name=filter_name, enabled=True)
            if not rules:
                console.print(f"[red]Rule '{filter_name}' not found or not enabled![/red]")
                return
        else:
            rules = AnsibleFilterRule.objects(enabled=True)

        if not rules:
            console.print("[yellow]No enabled filter rules found![/yellow]")
            return

        console.print(f"\n[green]Testing {rules.count()} filter rule(s)...[/green]\n")

        attribute_filter = Filter()
        attribute_filter.cache_name = 'ansible_filter_debug'
        attribute_filter.rules = rules.order_by('sort_field')

        hosts = Host.objects()
        total_hosts = hosts.count()

        console.print(f"Total hosts in database: {total_hosts}\n")

        matched_table = Table(title="Hosts MATCHED by Filter (will be processed)")
        matched_table.add_column("Hostname", style="cyan")
        matched_table.add_column("Labels", style="yellow")

        ignored_table = Table(title="Hosts NOT matched (ignored by filter)")
        ignored_table.add_column("Hostname", style="cyan")
        ignored_table.add_column("Labels", style="yellow")

        matched_count = 0
        ignored_count = 0

        for db_host in hosts:
            hostname = db_host.hostname
            labels = str(db_host.labels)[:50] if db_host.labels else ""

            attributes = attribute_filter.get_outcomes(db_host, db_host.labels)

            if attributes.get('ignore_host'):
                ignored_count += 1
                if show_ignored:
                    ignored_table.add_row(hostname, labels)
            else:
                matched_count += 1
                if show_matched:
                    matched_table.add_row(hostname, labels)

        console.print(f"[green]Matched (will be processed): {matched_count}[/green]")
        console.print(f"[red]Ignored (filtered out): {ignored_count}[/red]")

        if matched_count > 0 and show_matched:
            console.print("\n")
            console.print(matched_table)

        if ignored_count > 0 and show_ignored:
            console.print("\n")
            console.print(ignored_table)

register_cronjob('Ansible: Build Cache', _inner_update_cache)

# Iniate API
from syncerapi.v1.rest import API

from .rest_api.ansible import API as ansible
API.add_namespace(ansible, path='/ansible')