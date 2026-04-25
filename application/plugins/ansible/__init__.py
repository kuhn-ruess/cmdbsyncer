"""
Ansible Inventory Modul
"""
import json
import os
import click

from mongoengine.errors import DoesNotExist

from rich.console import Console
from rich.table import Table

from application import app
from application.models.host import Host
from application.modules.debug import ColorCodes, attribute_table, \
                                    apply_debug_rules, clear_host_debug_cache
from application.modules.rule.filter import Filter
from application.modules.rule.rewrite import Rewrite
from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group
from application.modules.inventory import (
    register_inventory_provider,
    register_inventory_provider_resolver,
)

from .models import AnsibleFilterRule, AnsibleRewriteAttributesRule, \
                    AnsibleCustomVariablesRule, AnsibleProject
from .rules import AnsibleVariableRule
from .inventory import AnsibleInventory
from .site_syncer import SyncSites

cli_ansible = register_cli_group(app, 'ansible', 'ansible',
                                 "Ansible Datasource and Debug")

#   .-- Load Rules
def load_rules(project=None):
    """
    Cache the rules feeding one Ansible inventory pass.

    `project=None` (default) selects rules without a project assignment
    — that's the legacy / global behaviour, served by the `ansible`
    provider. Pass an `AnsibleProject` to load only that project's
    rules (strict isolation).

    The cache_name is namespaced per project so a cached run for the
    `ansible` provider cannot leak into a per-project run on the same
    host record.
    """
    project_suffix = f'_{project.name}' if project else ''
    rule_filter = {'enabled': True, 'project': project}

    attribute_filter = Filter()
    attribute_filter.cache_name = f'ansible_filter{project_suffix}'
    attribute_filter.rules = AnsibleFilterRule.objects(**rule_filter).order_by('sort_field')

    attribute_rewrite = Rewrite()
    attribute_rewrite.cache_name = f'ansible_rewrite{project_suffix}'
    attribute_rewrite.rules = \
            AnsibleRewriteAttributesRule.objects(**rule_filter).order_by('sort_field')

    ansible_rules = AnsibleVariableRule()
    ansible_rules.rules = \
            AnsibleCustomVariablesRule.objects(**rule_filter).order_by('sort_field')

    return {
        'filter': attribute_filter,
        'rewrite': attribute_rewrite,
        'actions': ansible_rules,
    }
#.
#   .-- Debug Host — shared backend for CLI + HTML debug page
def get_ansible_debug_data(hostname):
    """Return debug data (attributes, extra_attributes, rule_logs) for `hostname`.

    Mirrors `get_device_debug_data` (Netbox) and `get_host_debug_data`
    (Checkmk) so the HTML debug view can reuse the shared renderer. The
    CLI variant (`debug_ansible_rules`) uses the same data but prints
    to stdout.
    """
    rules = load_rules()
    rule_logs = {}

    syncer = AnsibleInventory()
    apply_debug_rules(syncer, rules)

    db_host = clear_host_debug_cache(hostname, 'ansible')
    if not db_host:
        return None, None, None

    attributes = syncer.get_attributes(db_host, 'ansible')
    extra_attributes = {}
    if attributes:
        hidden_fields = ('ansible_password', 'ansible_ssh_pass')
        extra_attributes = syncer.get_host_data(db_host, attributes['all']) or {}
        for key in list(extra_attributes.keys()):
            if key in hidden_fields:
                value = extra_attributes[key] or ''
                extra_attributes[key] = f"HIDDEN...{value[-3:]}" if value else 'HIDDEN'

    rule_logs['CustomAttributes'] = syncer.custom_attributes.debug_lines
    rule_logs['filter'] = rules['filter'].debug_lines
    rule_logs['rewrite'] = rules['rewrite'].debug_lines
    rule_logs['actions'] = rules['actions'].debug_lines

    return attributes, extra_attributes, rule_logs


@cli_ansible.command('debug_host')
@click.argument("hostname")
def debug_ansible_rules(hostname):
    """
    Print matching rules and Inventory Outcome for Host
    """
    rules = load_rules()

    syncer = AnsibleInventory()
    apply_debug_rules(syncer, rules)

    db_host = clear_host_debug_cache(hostname, 'ansible')
    if not db_host:
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
    # pylint: disable=unused-argument
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
@click.option("--list", "show_list", is_flag=True)
@click.option("--host")
def source(show_list, host):
    """Inventory Source for Ansible"""
    rules = load_rules()
    syncer = AnsibleInventory()
    syncer.filter = rules['filter']
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['actions']

    if show_list:
        print(json.dumps(syncer.get_full_inventory()))
        return True
    if host:
        print(json.dumps(syncer.get_host_inventory(host)))
        return True
    print("Params missing")
    return False
#.
#   .-- Checkmk Server Source
@cli_ansible.command('cmk-server-source')
@click.option("--list", "show_list", is_flag=True)
@click.option("--host")
def server_source(show_list, host):
    """Inventory Source for Checkmk Server Data"""
    cmksitemngmt = SyncSites()
    if show_list:
        print(json.dumps(cmksitemngmt.get_full_inventory()))
        return True
    if host:
        print(json.dumps(cmksitemngmt.get_host_inventory(host)))
        return True
    print("Params missing")
    return False

#.
#   .-- Debug Filter
@cli_ansible.command('debug_filter')
@click.option('--list-rules', '-l', is_flag=True, help='List all available filter rules')
@click.option('--filter-name', '-f', default=None, help='Name of specific filter rule to test')
@click.option('--show-matched', '-m', is_flag=True,
              help='Show hosts matched by filter (will be processed)')
@click.option('--show-ignored', '-i', is_flag=True,
              help='Show hosts NOT matched (ignored by filter)')
def debug_filter(list_rules, filter_name, show_matched, show_ignored):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
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


# .--- Inventory provider registration
# Both the CLI host inventory and the Checkmk-Sites inventory go through
# the cross-module registry so the unified
# `cmdbsyncer inventory ansible <provider>` CLI / `/api/v1/inventory/ansible`
# HTTP endpoint can serve them — and so other modules can register their
# own providers later without touching the Ansible plugin.
def _build_ansible_provider(project=None):
    """
    Fully configured AnsibleInventory rendered through `project`'s rules
    (or the global / project-less rules when `project` is None).
    """
    rules = load_rules(project=project)
    syncer = AnsibleInventory()
    syncer.filter = rules['filter']
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['actions']
    return syncer


def _build_cmk_sites_provider():
    """Checkmk-Sites inventory used by the cmk_server_mngmt.yml playbook."""
    return SyncSites()


register_inventory_provider('ansible', _build_ansible_provider)
register_inventory_provider('cmk_sites', _build_cmk_sites_provider)


class _AnsibleProjectResolver:
    """
    Resolve dynamic provider names to per-project AnsibleInventory
    factories. Registered once at app startup; the lookup happens per
    request, so projects added or disabled at runtime via the admin UI
    take effect on the next inventory call without an app restart.
    """

    def __call__(self, name):
        """Return a factory for `name` if it is a known project, else None."""
        project = AnsibleProject.objects(name=name, enabled=True).first()
        if project is None:
            return None
        return lambda p=project: _build_ansible_provider(project=p)

    def list_names(self):
        """Project names currently enabled — exposed via the registry's listing API."""
        return [p.name for p in AnsibleProject.objects(enabled=True).only('name')]


register_inventory_provider_resolver(_AnsibleProjectResolver())
# .---



from .playbook_rules import fire_playbook_rules  # pylint: disable=wrong-import-position


@cli_ansible.command('fire_playbook_rules')
def cli_fire_playbook_rules():
    """
    Evaluate AnsiblePlaybookFireRule rules and dispatch playbook runs for
    any (rule, host, playbook) combination that has not yet been fired.
    """
    fired = fire_playbook_rules()
    print(f"{ColorCodes.OKGREEN}Dispatched {fired} playbook run(s){ColorCodes.ENDC}")


register_cronjob('Ansible: Fire Playbook Rules', fire_playbook_rules)


# Initiate REST API namespace — only when the web layer is being built.
# In CLI mode ``application.api.views`` is intentionally not loaded, so
# pulling ``syncerapi.v1.rest`` (which re-exports ``API`` from there)
# would drag the whole flask-restx stack back in for nothing.
if os.environ.get('CMDBSYNCER_CLI') != '1':
    from syncerapi.v1.rest import API  # pylint: disable=wrong-import-position,wrong-import-order
    from .rest_api.ansible import API as ansible  # pylint: disable=wrong-import-position
    API.add_namespace(ansible, path='/ansible')
