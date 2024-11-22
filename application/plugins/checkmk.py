"""
Commands to handle Checkmk Sync
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get, no-member

import click
from mongoengine.errors import DoesNotExist
from application import log
from application.modules.checkmk.syncer import SyncCMK2
from application.modules.checkmk.cmk2 import cli_cmk
from application.helpers.cron import register_cronjob
from application.modules.debug import ColorCodes, attribute_table


from application.modules.rule.filter import Filter
from application.modules.checkmk.models import CheckmkFilterRule

from application.modules.rule.rewrite import Rewrite
from application.modules.checkmk.models import CheckmkRewriteAttributeRule

from application.modules.checkmk.rules import CheckmkRule
from application.modules.checkmk.models import CheckmkRule as CheckmkRuleModel

from application.models.host import Host

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
@click.option("--disabled_only", is_flag=True)
def show_hosts(disabled_only=False):
    """
    Print List of all Hosts currently synced to Checkmk
    Disabled_only means: All hosts not configured to sync to Checkmk

    ### Example
    _./cmdbsyncer checkmk show_hosts_

    Args:
        disabled_only (bool): Only not synced hosts
    """
    rules = _load_rules()
    syncer = SyncCMK2()
    syncer.filter = rules['filter']
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['actions']


    for db_host in Host.get_export_hosts():
        attributes = syncer.get_host_attributes(db_host, 'checkmk')
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
    rules = _load_rules()
    syncer = SyncCMK2()
    syncer.filter = rules['filter']
    syncer.rewrite = rules['rewrite']
    syncer.actions = rules['actions']

    outcome = []
    for db_host in Host.get_export_hosts():
        attributes = syncer.get_host_attributes(db_host, 'checkmk')
        if not attributes:
            continue

        for key, value in attributes['filtered'].items():
            if (key, value) not in outcome:
                outcome.append((key, value))

    for key, value in outcome:
        print(f"{key}:{value}")
#.
#   .-- Command: Export Hosts
def _inner_export_hosts(account, limit=False, dry_run=False, save_requests=False):
    try:
        rules = _load_rules()
        syncer = SyncCMK2(account)
        syncer.dry_run = dry_run
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
        log.log(f"Export to Checkmk Account: {account} maybe not found FAILED",
        source="checkmk_host_export", details=[('error', str(error_obj))])
        print(f'{ColorCodes.FAIL}CMK Connection Error: {error_obj} {ColorCodes.ENDC}')


@cli_cmk.command('export_hosts')
@click.argument("account")
@click.option("--limit", default='')
#@click.option("--debug", default=False, is_flag=True)
@click.option("--dry-run", default=False, is_flag=True)
@click.option("--save-requests", default='')
def export_hosts(account, limit, dry_run, save_requests):
    """
    Export Hosts to Checkmk

    ### Example
    _./cmdbsyncer checkmk export_hosts SITEACCOUNT_

    Args:
        account (string): Name Account Config
        limit (list): Comma separted list of Hosts
    """

    _inner_export_hosts(account, limit, dry_run, save_requests)
#.
#   .-- Command: Host Debug

def get_debug_data(hostname):
    """
    Returns Debug Data
    """
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

    attributes = syncer.get_host_attributes(db_host, 'checkmk')

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
def debug_host(hostname):
    """
    Debug Host Configuration

    ### Example
    _./cmdbsyncer checkmk debug_host HOSTNAME_

    Args:
        hostname (string): Name of Host
    """

    try:
        attributes, actions, _debug_log  = get_debug_data(hostname)
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


register_cronjob('Checkmk: Export Hosts', _inner_export_hosts)
