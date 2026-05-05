"""
Inits for the Plugins
"""
from application import log
from application.plugins.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes
from application.models.host import Host
from application.modules.rule.filter import Filter

from application.plugins.checkmk.tags import CheckmkTagSync
from application.plugins.checkmk.cmk_rules import CheckmkRuleSync
from application.plugins.checkmk.downtimes import CheckmkDowntimeSync
from application.plugins.checkmk.rules import CheckmkRulesetRule, DefaultRule
from application.plugins.checkmk.inventorize import InventorizeHosts
from application.plugins.checkmk.dcd import CheckmkDCDRuleSync
from application.plugins.checkmk.passwords import CheckmkPasswordSync
from application.plugins.checkmk.groups import CheckmkGroupSync
from application.plugins.checkmk.users import CheckmkUserSync
from application.plugins.checkmk.bi import BI
from application.plugins.checkmk.sites import CheckmkSites



from application.modules.rule.rewrite import Rewrite
from application.plugins.checkmk.models import (
   CheckmkRuleMngmt,
   CheckmkBiRule,
   CheckmkBiAggregation,
   CheckmkDowntimeRule,
   CheckmkRewriteAttributeRule,
   CheckmkFilterRule,
   CheckmkDCDRule,
   CheckmkFolderPool,
)



def _load_rules():
    """
    Load needed extra Rules
    """
    attribute_rewrite = Rewrite()
    attribute_rewrite.cache_name = 'checkmk_rewrite'
    attribute_rewrite.rules = \
                    CheckmkRewriteAttributeRule.objects(enabled=True).order_by('sort_field')

    attribute_filter = Filter()
    attribute_filter.cache_name = "checkmk_filter"
    attribute_filter.rules = CheckmkFilterRule.objects(enabled=True).order_by('sort_field')

    return {
        'rewrite': attribute_rewrite,
        'filter': attribute_filter,
    }

#   .-- Export Tags
def export_tags(account, dry_run=False, save_requests=False, debug=False):
    """
    Export Tags to Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        syncer = CheckmkTagSync(account)
        syncer.debug = debug
        syncer.rewrite = rules['rewrite']
        syncer.filter = rules['filter']
        syncer.dry_run = dry_run
        syncer.save_requests = save_requests
        syncer.name = 'Checkmk: Export Tags'
        syncer.source = "cmk_tag_sync"
        syncer.export_tags()
    except Exception as error_obj:  # pylint: disable=broad-exception-caught
        if debug:
            raise
        print(f'{ColorCodes.FAIL}Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Tags to Account {account} not started",
                    source="cmk_tag_sync", details=[('error', str(error_obj))])

#.
#   .-- Export BI Rules
def export_bi_rules(account, debug):
    """
    Export BI Rules to Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        syncer = BI(account)
        syncer.rewrite = rules['rewrite']
        syncer.filter = rules['filter']
        syncer.debug = debug

        class ExportBiRule(DefaultRule):
            """
            Name overwrite
            """

        actions = ExportBiRule()
        actions.rules = CheckmkBiRule.objects(enabled=True)
        syncer.actions = actions
        syncer.name = 'Checkmk: Export BI Rules'
        syncer.source = "cmk_bi_sync"
        syncer.export_bi_rules()
    except CmkException as error_obj:
        if debug:
            raise
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export BI Rules to Account {account} not started",
                    source="cmk_bi_sync", details=[('error', str(error_obj))])
#.
#   .-- Export BI Aggregations
def export_bi_aggregations(account, debug):
    """
    Export BI Aggregations to Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        syncer = BI(account)
        syncer.rewrite = rules['rewrite']
        syncer.filter = rules['filter']
        syncer.debug = debug
        # Set name + source BEFORE the work runs so the atexit save_log
        # entry is identifiable even if the work raises.
        syncer.name = 'Checkmk: Export BI Aggregations'
        syncer.source = "cmk_bi_aggrigation_sync"
        class ExportBiAggr(DefaultRule):
            """
            Name overwrite
            """
        actions = ExportBiAggr()
        actions.rules = CheckmkBiAggregation.objects(enabled=True)
        syncer.actions = actions
        syncer.export_bi_aggregations()
    except CmkException as error_obj:
        if debug:
            raise
        print(f'{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export BI Aggregations to Account {account} not started",
                    source="cmk_bi_aggrigation_sync",
                    details=[('error', str(error_obj))])

#.
#   .-- Inventorize Hosts


def inventorize_hosts(account, debug=False):
    """
    Inventorize information from Checkmk Installation
    """
    inven = None
    try:
        inven = InventorizeHosts(account)
        inven.debug = debug
        inven.run()
    except CmkException as error_obj:
        if debug:
            raise
        print(f'{ColorCodes.FAIL} Error: {error_obj} {ColorCodes.ENDC}')
        if inven is not None:
            inven.record_exception(error_obj)
        else:
            log.log(f"Inventorize Hosts Account {account} not started",
                    source="checkmk_inventorize",
                    details=[('error', str(error_obj))])

#.
#   . -- Show missing hosts
def show_missing(account):
    """
    Return list of all currently missing hosts
    """
    cmk = CMK2(account)

    local_hosts = [x.hostname for x in Host.get_export_hosts()]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{account}{ColorCodes.ENDC}")
    url = "domain-types/host_config/collections/all?effective_attributes=false"
    api_hosts = cmk.request(url, method="GET")
    for host in api_hosts[0]['value']:
        hostname = host['id']
        if hostname not in local_hosts:
            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} {hostname}")

#.
#   . -- Bake and Sign Agents
def bake_and_sign_agents(account):
    """
    Bake and Sign Agents in Checkmk
    """
    from application.helpers.get_account import get_account_by_name  # pylint: disable=import-outside-toplevel
    account_config = get_account_by_name(account)
    if account_config['typ'] != 'cmkv2':
        print(f"{ColorCodes.FAIL} Not a Checkmk 2.x Account {ColorCodes.ENDC}")
        return False
    if "bakery_key_id" not in account_config and "bakery_passphrase" not in account_config:
        print(f"{ColorCodes.FAIL} Please set bakery_key_id and "\
              f"bakery_passphrase as Custom Account Config {ColorCodes.ENDC}")
        return False
    cmk = CMK2(account)
    url = "/domain-types/agent/actions/bake_and_sign/invoke"
    data = {
        'key_id': int(account_config['bakery_key_id']),
        'passphrase': account_config['bakery_passphrase'],
    }
    try:
        cmk.request(url, data=data, method="POST")
        print("Signed and Baked Agents")
        return True
    except CmkException as errors:
        print(errors)
        return False
#.
#   .-- Activate Changes
def activate_changes(account):
    """
    Activate Changes of Checkmk Instance
    """
    cmk = CMK2(account)

    # Get current activation etag
    url = "/domain-types/activation_run/collections/pending_changes"
    data, headers = cmk.request(url, "GET")
    etag = headers.get('ETag')
    if cmk.config.get('dont_activate_changes_if_more_then'):
        user = cmk.config['username']
        num_changes = len([x['user_id'] for x in data['value'] if x['user_id'] == user])
        if num_changes > int(cmk.config['dont_activate_changes_if_more_then']):
            print(f"{ColorCodes.FAIL}Too many changes to activate: {num_changes} > "\
                  f"{cmk.config['dont_activate_changes_if_more_then']}{ColorCodes.ENDC}")
            details = [('error', f'Too many changes to activate: {num_changes} > '\
                             f'{cmk.config["dont_activate_changes_if_more_then"]}')]
            log.log("Activate Changes aborted, too many changes",
                    source="Checkmk", details=details)
            return False

    update_headers = {
        'if-match': etag
    }

    # Trigger Activate Changes
    url = "/domain-types/activation_run/actions/activate-changes/invoke"
    data = {
        'redirect': False,
        'force_foreign_changes': True,
    }
    try:
        cmk.request(url,
                    data=data,
                    method="POST",
                    additional_header=update_headers,
        )
        print("Changes activated")
    except CmkException as errors:
        print(errors)
    return True
#.
#   .-- Export Groups
def export_groups(account, test_run=False, debug=False):
    """
    Manage Groups in Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        syncer = CheckmkGroupSync(account)
        syncer.debug = debug
        syncer.rewrite = rules['rewrite']
        syncer.filter = rules['filter']
        syncer.name = 'Checkmk: Export Groups'
        syncer.source = "cmk_group_sync"
        syncer.export_cmk_groups(test_run)
    except CmkException as error_obj:
        if debug:
            raise
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Groups to Account {account} not started",
                    source="cmk_group_sync",
                    details=[('error', str(error_obj))])
#.
#   .-- Export Rules
def export_rules(account):
    """
    Create Rules in Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        syncer = CheckmkRuleSync(account)
        syncer.filter = rules['filter']
        syncer.rewrite = rules['rewrite']

        actions = CheckmkRulesetRule()
        # Process rules in their configured ``sort_field`` order so the
        # resulting outcomes feed into ``rulsets_by_type`` already
        # ordered. The Checkmk-side reorder step (``sort_rules``) then
        # only needs to chain ``after_specific_rule`` moves to lock the
        # order into Checkmk's ruleset.
        actions.rules = CheckmkRuleMngmt.objects(enabled=True).order_by('sort_field')
        syncer.actions = actions
        syncer.name = 'Checkmk: Export Rules'
        syncer.source = "cmk_rule_sync"
        syncer.export_cmk_rules()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Rules to Account {account} not started",
                    source="cmk_rule_sync",
                    details=[('error', str(error_obj))])
#.
#   .-- Export Downtimes
def export_downtimes(account, debug=False, debug_rules=False):
    """
    Create Rules in Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        class ExportDowntimes(DefaultRule):
            """
            Name overwrite
            """
        actions = ExportDowntimes()
        actions.rules = CheckmkDowntimeRule.objects(enabled=True)

        if not debug_rules:
            syncer = CheckmkDowntimeSync(account)
            syncer.rewrite = rules['rewrite']
            syncer.filter = rules['filter']

            syncer.actions = actions
            syncer.name = 'Checkmk: Export Downtimes'
            syncer.source = "cmk_downtime_sync"
            syncer.run()
        else:
            syncer = CheckmkDowntimeSync(False)
            syncer.rewrite = rules['rewrite']
            syncer.filter = rules['filter']
            syncer.actions = actions
            syncer.debug_rules(debug_rules, "Checkmk")

    except CmkException as error_obj:
        if debug:
            raise
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Downtimes to Account {account} not started",
                    source="cmk_downtime_sync",
                    details=[('error', str(error_obj))])
#.
#   . DCD Rules
def export_dcd_rules(account, debug=False, debug_rules=False):
    """
    Export DCD Rules to Checkmk
    """
    syncer = None
    try:
        rules = _load_rules()
        class ExportDCD(DefaultRule):
            """
            Name overwrite
            """
        actions = ExportDCD(account)
        actions.rules = CheckmkDCDRule.objects(enabled=True)

        if not debug_rules:
            syncer = CheckmkDCDRuleSync(account)
            syncer.debug = debug
            syncer.actions = actions
            syncer.rewrite = rules['rewrite']
            syncer.filter = rules['filter']
            syncer.name = 'Checkmk: Export DCD Rules'
            syncer.source = "cmk_dcd_rule_sync"
            syncer.export_rules()
        else:
            syncer = CheckmkDCDRuleSync(False)
            syncer.actions = actions
            syncer.rewrite = rules['rewrite']
            syncer.filter = rules['filter']
            syncer.debug_rules(debug_rules, "Checkmk")

    except CmkException as error_obj:
        if debug:
            raise
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export DCD Rules to Account {account} not started",
                    source="cmk_dcd_rule_sync",
                    details=[('error', str(error_obj))])
#.
#   . Passwords
def export_passwords(account):
    """
    Export Passwords to Checkmk
    """
    syncer = None
    try:
        syncer = CheckmkPasswordSync(account)
        syncer.export_passwords()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Passwords to Account {account} not started",
                    source="cmk_password_sync",
                    details=[('error', str(error_obj))])
#.
#   . Import Sites
def import_sites(account):
    """Import Checkmk sites of ``account`` into the local Object table."""
    syncer = None
    try:
        syncer = CheckmkSites(account)
        syncer.import_sites()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Import Sites from Account {account} not started",
                    source="cmk_site_sync",
                    details=[('error', str(error_obj))])
#   . Export Users
def export_users(account):
    """
    Export configured Users to Checkmk
    """
    syncer = None
    try:
        syncer = CheckmkUserSync(account)
        syncer.export_users()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        if syncer is not None:
            syncer.record_exception(error_obj)
        else:
            log.log(f"Export Users to Account {account} not started",
                    source="cmk_user_sync",
                    details=[('error', str(error_obj))])
#.
#   . Sync Folder Pools
def sync_folderpools(_account=False, _debug=False):
    """Refresh ``folder_seats_taken`` on every CheckmkFolderPool from current host counts."""
    pool_usage = {}
    # Folder-pool counts only matter for hosts that ship to Checkmk —
    # anything not 'active' won't take a seat on the next sync.
    for host in Host.get_export_hosts():
        if host.folder:
            pool_usage.setdefault(host.folder, 0)
            pool_usage[host.folder] += 1

    for pool_folder, usage in pool_usage.items():
        print(f"Folder {pool_folder} uses {usage} seats")
        folder = CheckmkFolderPool.objects.get(folder_name=pool_folder)
        if folder.folder_seats_taken != usage:
            print(f" - Changed seats from {folder.folder_seats_taken} to {usage}")
            folder.folder_seats_taken = usage
            folder.save()
        else:
            print(" - Is already up to date")
#.
