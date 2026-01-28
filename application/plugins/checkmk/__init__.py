"""
Commands to handle Checkmk Sync
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get, no-member

import click
from mongoengine.errors import DoesNotExist
from application import log
from .cmk2 import cli_cmk, CmkException
from application.helpers.cron import register_cronjob
from application.modules.debug import ColorCodes, attribute_table


from application.modules.rule.filter import Filter
from .models import CheckmkFilterRule

from application.modules.rule.rewrite import Rewrite
from .models import CheckmkRewriteAttributeRule

from .rules import CheckmkRule
from .models import CheckmkRule as CheckmkRuleModel

from .inits import (
    export_bi_rules,
    export_bi_aggregations,
    export_rules,
    export_groups,
    activate_changes,
    bake_and_sign_agents,
    inventorize_hosts,
    show_missing,
    export_users,
    export_tags,
    export_downtimes,
    export_dcd_rules,
    export_passwords,
    import_sites,
)

def _load_rules():
    """
    Cache all needed Rules for operation
    """
    attribute_filter = Filter()
    attribute_filter.cache_name = "checkmk_filter"
    attribute_filter.rules = CheckmkFilterRule.objects(enabled=True).order_by('sort_field')

    attribute_rewrite = Rewrite()
    attribute_rewrite.cache_name = 'checkmk_rewrite'
    attribute_rewrite.rules = \
                    CheckmkRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

    checkmk_rules = CheckmkRule()
    checkmk_rules.rules = CheckmkRuleModel.objects(enabled=True).order_by('sort_field')
    return {
        'filter': attribute_filter,
        'rewrite': attribute_rewrite,
        'actions': checkmk_rules
    }

#   . -- Command: Show Hosts
@cli_cmk.command('show_hosts')
@click.option("--disabled-only", is_flag=True)
def show_hosts(disabled_only=False):
    """
    Print List of all Hosts currently synced to Checkmk
    Disabled_only means: All hosts not configured to sync to Checkmk

    ### Example
    _./cmdbsyncer checkmk show_hosts_

    Args:
        disabled_only (bool): Only not synced hosts
    """
    from .syncer import SyncCMK2
    from application.models.host import Host

    rules = _load_rules()
    syncer = SyncCMK2()
    syncer.filter = rules['filter']
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['actions']


    for db_host in Host.get_export_hosts():
        attributes = syncer.get_attributes(db_host, 'checkmk')
        if not attributes:
            if disabled_only:
                print(db_host.hostname)
            continue
        if not disabled_only:
            print(db_host.hostname, attributes['filtered'])
#.
#   . -- Show Labels
@cli_cmk.command('show_labels')
def show_labels():
    """
    Print unique list of labels which later will be in Checkmk

    ### Example
    _./cmdbsyncer checkmk show_labels_
    """
    from .syncer import SyncCMK2
    from application.models.host import Host

    rules = _load_rules()
    syncer = SyncCMK2()
    syncer.filter = rules['filter']
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['actions']

    outcome = []
    for db_host in Host.get_export_hosts():
        attributes = syncer.get_attributes(db_host, 'checkmk')
        if not attributes:
            continue

        for key, value in attributes['filtered'].items():
            if (key, value) not in outcome:
                outcome.append((key, value))

    for key, value in outcome:
        print(f"{key}:{value}")
#.
#   .-- Command: Export Hosts
def _inner_export_hosts(account, limit=False, debug=False, dry_run=False, save_requests=False):
    try:
        from .syncer import SyncCMK2
        rules = _load_rules()
        syncer = SyncCMK2(account)
        syncer.dry_run = dry_run
        syncer.debug = debug
        syncer.save_requests = save_requests
        if limit:
            syncer.config['limit_by_hostnames'] = limit

        syncer.filter = rules['filter']
        syncer.rewrite = rules['rewrite']
        syncer.actions = rules['actions']
        syncer.name = "Checkmk: Export Hosts"
        syncer.source = "cmk_host_sync"
        syncer.run()
    except Exception as error_obj:
        if debug:
            raise
        log.log(f"Export to Checkmk Account: {account} maybe not found FAILED",
        source="checkmk_host_export", details=[('error', str(error_obj))])
        print(f'{ColorCodes.FAIL}CMK Connection Error: {error_obj} {ColorCodes.ENDC}')


@cli_cmk.command('export_hosts')
@click.argument("account")
@click.option("--limit", default='')
@click.option("--debug", default=False, is_flag=True)
@click.option("--dry-run", default=False, is_flag=True)
@click.option("--save-requests", default='')
def export_hosts(account, limit, debug, dry_run, save_requests):
    """
    Export Hosts to Checkmk

    ### Example
    _./cmdbsyncer checkmk export_hosts SITEACCOUNT_

    Args:
        account (string): Name Account Config
        limit (list): Comma separted list of Hosts
    """

    _inner_export_hosts(account, limit, debug, dry_run, save_requests)
#.
#   .-- Command: Host Debug

def get_host_debug_data(hostname):
    """
    Returns Debug Data
    """
    from .syncer import SyncCMK2
    from application.models.host import Host

    rules = _load_rules()

    rule_logs = {}

    syncer = SyncCMK2()
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
            if key.lower().startswith('checkmk'):
                del db_host.cache[key]
        if 'CustomAttributeRule' in db_host.cache:
            del db_host.cache['CustomAttributeRule']
        db_host.save()
    except DoesNotExist:
        print(f"{ColorCodes.FAIL}Host not Found{ColorCodes.ENDC}")
        raise

    attributes = syncer.get_attributes(db_host, 'checkmk')

    if attributes:
        actions = syncer.get_host_actions(db_host, attributes['all'])
    else:
        actions = {}


    rule_logs['CustomAttributes'] = syncer.custom_attributes.debug_lines
    rule_logs['filter'] = rules['filter'].debug_lines
    rule_logs['rewrite'] = rules['rewrite'].debug_lines
    rule_logs['actions'] = rules['actions'].debug_lines

    # We need to save the host,
    # Otherwise, if a rule with folder pools is executed at first time here,
    # the seat will be locked, but not saved by the host
    db_host.save()

    return attributes, actions, rule_logs


@cli_cmk.command('debug_host')
@click.argument("hostname")
@click.option("--debug", default=False, is_flag=True)
def debug_host(hostname, debug):
    """
    Debug Host Configuration

    ### Example
    _./cmdbsyncer checkmk debug_host HOSTNAME_

    Args:
        hostname (string): Name of Host
    """

    try:
        attributes, actions, _debug_log  = get_host_debug_data(hostname)
    except DoesNotExist:
        return

    if not attributes:
        print(f"{ColorCodes.FAIL}THIS HOST IS IGNORED BY RULE{ColorCodes.ENDC}")
        return

    attribute_table("Full Attribute List", attributes['all'])
    attribute_table("Filtered Labels for Checkmk", attributes['filtered'])
    attribute_table("Actions", actions)
    additional_attributes = {}
    additional_attributes =  actions.get('custom_attributes', {})

    for additional_attr in actions.get('attributes',[]):
        if attr_value := attributes['all'].get(additional_attr):
            additional_attributes[additional_attr] = attr_value

    if 'remove_attributes' in actions and 'remove_attributes' in additional_attributes:
        # Do not show Removed Attributes in the Custom Attributes list
        for del_attr in additional_attributes['remove_attributes']:
            try:
                del additional_attributes[del_attr]
            except KeyError:
                pass
    attribute_table("Custom Attributes", additional_attributes)


#.
#   .-- Command: Export Downtimes
@cli_cmk.command('export_downtimes')
@click.option("--debug", is_flag=True)
@click.option("--debug-rules", default="")
@click.argument('account')
#pylint: disable=too-many-locals
def cli_export_downtimes(account, debug, debug_rules):
    """
    Export Dowtimes to Checkmk

    ### Example
    _./cmdbsyncer checkmk export_downtimes SITEACCOUNT_

    Args:
        account (string): Name Checkmk Account Config
    """
    export_downtimes(account, debug, debug_rules)



#.
#   .-- Command: Export Tags
@cli_cmk.command('export_tags')
@click.argument('account')
@click.option("--dry-run", default=False, is_flag=True)
@click.option("--save-requests", default='')
@click.option("--debug", is_flag=True)
#pylint: disable=too-many-locals
def cli_export_tags(account, dry_run, save_requests, debug=False):
    """
    Export Hosttags Groups to Checkmk

    ### Example
    _./cmdbsyncer checkmk show_missing_hosts SITEACCOUNT_

    Args:
        account (string): Name Checkmk Account Config
    """
    export_tags(account, dry_run, save_requests, debug)

#.
#   .-- Command: Show Hosts not in Syncer
@cli_cmk.command('show_missing_hosts')
@click.argument('account')
#pylint: disable=too-many-locals
def cli_missing_hosts(account):
    """
    Check which Hosts are in Checkmk but not in Syncer

    ### Example
    _./cmdbsyncer checkmk show_missing_hosts SITEACCOUNT_

    Args:
        account (string): Name Checkmk Account Config
    """
    show_missing(account)
#.
#   .-- Command: Export Rulesets

@cli_cmk.command('export_rules')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cli_export_rules(account, debug):
    """
    Export all configured Rules to given Checkmk Installations

    ### Example
    _./cmdbsyncer checkmk export_rules SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_rules(account)

#.
#   .-- Command: Export Group
@cli_cmk.command('export_groups')
@click.argument("account")
@click.option('-t', '--test-run', is_flag=True)
@click.option("--debug", is_flag=True)
#pylint: disable=too-many-locals, too-many-branches
def cli_export_groups(account, test_run, debug=False):
    """
    Create Groups in Checkmk

    ### Example
    _./cmdbsyncer checkmk export_groups SITEACCOUNT_


    Args:
        account (string): Name Account Config
        test_run (bool): Only Print Result ( default is False )
    """
    export_groups(account, test_run, debug)


#.
#   .-- Command: Activate Changes
@cli_cmk.command('activate_changes')
@click.argument("account")
#pylint: disable=too-many-locals, too-many-branches
def cli_activate_changes(account):
    """
    Activate Changes in given Checkmk Instance

    ### Example
    _./cmdbsyncer checkmk activate_changes SITEACCOUNT_


    Args:
        account (string): Name CHeckmk Account Config
    """
    activate_changes(account)



#.
#   .-- Command: Bake and Sign agents
@cli_cmk.command('bake_and_sign_agents')
@click.argument("account")
#pylint: disable=too-many-locals, too-many-branches
def cli_bake_and_sign_agents(account):
    """
    Bake and Sign Agents for given Checkmk Instance

    ### Example
    _./cmdbsyncer checkmk bake_and_sign_agents SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    bake_and_sign_agents(account)

#.
#   .-- Command: Host Inventory

@cli_cmk.command('inventorize_hosts')
@click.argument('account')
@click.option("--debug", is_flag=True)
#pylint: disable=too-many-locals
def cli_inventorize_hosts(account, debug=False):
    """
    Do an Status Data inventory on given Checkmk Instance.
    Requires CMK Version greater then 2.1p9

    ### Example
    _./cmdbsyncer checkmk inventorize_hosts SITEACCOUNT_

    Args:
        account (string): Name Checkmk Account Config
    """
    inventorize_hosts(account, debug)
#.
#   .-- Command: Checkmk BI

@cli_cmk.command('export_bi_rules')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cli_export_bi_rules(account, debug=False):
    """
    Export all BI Rules to given Checkmk Installations

    ### Example
    _./cmdbsyncer checkmk export_bi_rules SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_bi_rules(account, debug)

@cli_cmk.command('export_bi_aggregations')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cli_export_bi_aggregations(account, debug=False):
    """
    Export all BI Aggregations to given Checkmk Installations

    ### Example
    _./cmdbsyncer checkmk export_bi_aggregations SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_bi_aggregations(account, debug)
#.
#   .-- Command: Export User
@cli_cmk.command('export_users')
@click.argument("account")
def cli_cmk_users(account):
    """
    Export configured Users and their settings to Checkmk

    ### Example
    _./cmdbsyncer checkmk export_users SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_users(account)
#.
#   .-- Command: Export DCD Rules
@cli_cmk.command('export_dcd_rules')
@click.option("--debug-rules", default="")
@click.option("--debug", is_flag=True)
@click.argument("account")
def cli_cmk_dcd(account, debug_rules, debug=False):
    """
    Export Rules for DCD Deamon

    ### Example
    _./cmdbsyncer checkmk export_dcd_rules SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_dcd_rules(account, debug, debug_rules)
#.
#   .-- Command: Export Passwords
@cli_cmk.command('export_passwords')
@click.argument("account")
def cli_cmk_passwords(account):
    """
    Export Rules for Password Export

    ### Example
    _./cmdbsyncer checkmk export_passwords SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    export_passwords(account)
#.
#   .-- Command: Import Sites
@cli_cmk.command('import_sites')
@click.argument("account")
def cli_cmk_import_istes(account):
    """
    Import Checkmk Sites into the Object Table

    ### Example
    _./cmdbsyncer checkmk import_sites SITEACCOUNT_


    Args:
        account (string): Name Checkmk Account Config
    """
    import_sites(account)
#.
#   .-- Import Checkmk V1
from .import_v1 import ImportCheckmk1
@cli_cmk.command('import_v1')
@click.argument("account")
def get_cmk_data(account):
    """Get All hosts from a CMK 1.x Installation and add them to local db"""
    from application.helpers.get_account import get_account_by_name
    source_config = get_account_by_name(account)
    if source_config:
        getter = ImportCheckmk1(source_config)
        getter.run()
    else:
        print("Source not found")
#.
#   .-- Import Checkmk V2
from .import_v2 import import_hosts
@cli_cmk.command('import_v2')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def get_cmk_data(account, debug=False):
    """Get All hosts from a CMK 2.x Installation and add them to local db"""
    try:
        import_hosts(account, debug)
    except CmkException as error_obj:
        if debug:
            raise
        print(f'CMK Connection Error: {error_obj}')
#.

register_cronjob('Checkmk: Export Hosts', _inner_export_hosts)
register_cronjob('Checkmk: Export Rules', export_rules)
register_cronjob('Checkmk: Export Groups', export_groups)
register_cronjob('Checkmk: Export BI Rules', export_bi_rules)
register_cronjob('Checkmk: Export BI Aggregations', export_bi_aggregations)
register_cronjob('Checkmk: Inventorize', inventorize_hosts)
register_cronjob('Checkmk: Activate Changes', activate_changes)
register_cronjob('Checkmk: Bake and Sign Agents', bake_and_sign_agents)
register_cronjob('Checkmk: Export Users', export_users)
register_cronjob('Checkmk: Export Tags', export_tags)
register_cronjob('Checkmk: Export Downtimes', export_downtimes)
register_cronjob('Checkmk: Export DCD Rules', export_dcd_rules)
register_cronjob('Checkmk: Export Passwords', export_passwords)
register_cronjob('Checkmk: Import Hosts (V2)', import_hosts)
register_cronjob('Checkmk: Import Sites', import_sites)
