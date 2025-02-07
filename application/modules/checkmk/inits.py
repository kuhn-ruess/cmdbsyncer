"""
Inits for the Plugins
"""
from application import log
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes
from application.models.host import Host
from application.modules.rule.filter import Filter

from application.modules.checkmk.tags import CheckmkTagSync
from application.modules.checkmk.cmk_rules import CheckmkRuleSync
from application.modules.checkmk.downtimes import CheckmkDowntimeSync
from application.modules.checkmk.rules import CheckmkRulesetRule, DefaultRule
from application.modules.checkmk.inventorize import InventorizeHosts
from application.modules.checkmk.dcd import CheckmkDCDRuleSync
from application.modules.checkmk.passwords import CheckmkPasswordSync
from application.modules.checkmk.groups import CheckmkGroupSync
from application.modules.checkmk.users import CheckmkUserSync
from application.modules.checkmk.bi import BI



from application.modules.rule.rewrite import Rewrite
from application.modules.checkmk.models import (
   CheckmkRuleMngmt,
   CheckmkBiRule,
   CheckmkBiAggregation,
   CheckmkDowntimeRule,
   CheckmkRewriteAttributeRule,
   CheckmkFilterRule,
   CheckmkDCDRule,
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
    details = []
    try:
        rules = _load_rules()
        syncer = CheckmkTagSync(account)
        syncer.debug = debug
        syncer.rewrite = rules['rewrite']
        syncer.dry_run = dry_run
        syncer.save_requests = save_requests
        syncer.name = 'Checkmk: Export Tags'
        syncer.source = "cmk_tag_sync"
        syncer.export_tags()
    except Exception as error_obj:
        print(f'{ColorCodes.FAIL}Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'Error: {error_obj}'))
        log.log(f"Exception Syncing Tags to Account: {account}",
                source="checkmk_tag_export",
                details=details)
        if debug:
            raise

#.
#   .-- Export BI Rules
def export_bi_rules(account):
    """
    Export BI Rules to Checkmk
    """
    details = []
    try:
        rules = _load_rules()
        syncer = BI(account)
        syncer.rewrite = rules['rewrite']

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
        details.append(('error', f'CMK Error: {error_obj}'))
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        log.log(f"Exception Export BI Rules to Checkmk Account: {account}",
                source="cmk_bi_sync", details=details)
#.
#   .-- Export BI Aggregations
def export_bi_aggregations(account):
    """
    Export BI Aggregations to Checkmk
    """
    details = []
    try:
        rules = _load_rules()
        syncer = BI(account)
        syncer.rewrite = rules['rewrite']
        class ExportBiAggr(DefaultRule):
            """
            Name overwrite
            """
        actions = ExportBiAggr()
        actions.rules = CheckmkBiAggregation.objects(enabled=True)
        syncer.actions = actions
        syncer.export_bi_aggregations()
        syncer.name = 'Checkmk: Export BI Aggregations'
        syncer.source = "cmk_bi_aggrigation_sync"
    except CmkException as error_obj:
        details.append(('error', f'CMK Error: {error_obj}'))
        print(f'{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        log.log(f"Export BI Aggregations to Checkmk Account: {account}",
                source="Checkmk", details=details)

#.
#   .-- Inventorize Hosts


def inventorize_hosts(account):
    """
    Inventorize information from Checkmk Installation
    """
    try:
        inven = InventorizeHosts(account)
        inven.run()
    except CmkException as error_obj:
        details = []
        details.append(('error', f'Error: {error_obj}'))
        print(f'{ColorCodes.FAIL} Error: {error_obj} {ColorCodes.ENDC}')
        log.log(f"Failure Inventorize Hosts Account: {account}",
                source="Checkmk", details=details)

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
    #pylint: disable = import-outside-toplevel
    from application.helpers.get_account import get_account_by_name
    account_config = get_account_by_name(account)
    if account_config['typ'] != 'cmkv2':
        print(f"{ColorCodes.FAIL} Not a Checkmk 2.x Account {ColorCodes.ENDC}")
        return False
    if "backery_key_id" not in account_config and "bakery_passphrase" not in account_config:
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
    _, headers = cmk.request(url, "GET")
    etag = headers.get('ETag')

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
    details = []
    try:
        rules = _load_rules()
        syncer = CheckmkGroupSync(account)
        syncer.debug = debug
        syncer.rewrite = rules['rewrite']
        syncer.name = 'Checkmk: Export Groups'
        syncer.source = "cmk_group_sync"
        syncer.export_cmk_groups(test_run)
    except CmkException as error_obj:
        if debug:
            raise
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
        log.log(f"Error Exporting Groups to Checkmk Account: {account}",
                source="Checkmk", details=details)
#.
#   .-- Export Rules
def export_rules(account):
    """
    Create Rules in Checkmk
    """
    details = []
    try:
        rules = _load_rules()
        syncer = CheckmkRuleSync(account)
        syncer.filter = rules['filter']

        syncer.rewrite = rules['rewrite']
        actions = CheckmkRulesetRule()
        actions.rules = CheckmkRuleMngmt.objects(enabled=True)
        syncer.actions = actions
        syncer.name = 'Checkmk: Export Rules'
        syncer.source = "cmk_rule_sync"
        syncer.export_cmk_rules()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
        log.log(f"Error exporting Rules to Checkmk Account: {account}",
                source="cmk_rule_sync", details=details)
#.
#   .-- Export Downtimes
def export_downtimes(account, debug=False, debug_rules=False):
    """
    Create Rules in Checkmk
    """
    details = []
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
            syncer.actions = actions
            syncer.name = 'Checkmk: Export Downtimes'
            syncer.source = "cmk_downtime_sync"
            syncer.run()
        else:
            syncer = CheckmkDowntimeSync(False)
            syncer.rewrite = rules['rewrite']
            syncer.actions = actions
            syncer.debug_rules(debug_rules, "Checkmk")

    except CmkException as error_obj:
        if debug:
            raise
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
        log.log(f"Export Downtimes to Checkmk Account: {account}",
                source="Checkmk", details=details)
#.
#   . DCD Rules
def export_dcd_rules(account, debug=False, debug_rules=False):
    """
    Export DCD Rules to Checkmk
    """
    details = []
    try:
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
            syncer.name = 'Checkmk: Export DCD Rules'
            syncer.source = "cmk_dcd_rule_sync"
            syncer.export_rules()
        else:
            syncer = CheckmkDCDRuleSync(False)
            syncer.actions = actions
            syncer.debug_rules(debug_rules, "Checkmk")


    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
        log.log(f"Error Exporing DCD Rules to Checkmk Account: {account}",
                source="cmk_dcd_rule_sync", details=details)
        if debug:
            raise
#.
#   . Passwords
def export_passwords(account):
    """
    Export Passwords to Checkmk
    """
    details = []
    try:
        syncer = CheckmkPasswordSync(account)
        syncer.export_passwords()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
        log.log(f"Error Exporting Passwords to Checkmk Account: {account}",
            source="cmk_password_sync", details=details)
#.
#   . Export Users
def export_users(account):
    """
    Export configured Users to Checkmk
    """
    details = []
    try:
        syncer = CheckmkUserSync(account)
        syncer.export_users()
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
        log.log(f"Error exporting Users to Checkmk Account: {account}",
                source="cmk_user_sync", details=details)
#.
