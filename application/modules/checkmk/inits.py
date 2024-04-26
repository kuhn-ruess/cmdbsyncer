"""
Inits for the Plugins
"""
from application import log
from application.helpers.get_account import get_account_by_name
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes
from application.models.host import Host
from application.modules.checkmk.config_sync import SyncConfiguration
from application.modules.checkmk.tags import CheckmkTagSync
from application.modules.checkmk.downtimes import CheckmkDowntimeSync
from application.modules.checkmk.rules import CheckmkRulesetRule, DefaultRule
from application.modules.rule.filter import Filter
from application.modules.checkmk.inventorize import InventorizeHosts
from application.modules.checkmk.models import CheckmkFilterRule

from application.modules.rule.rewrite import Rewrite
from application.modules.checkmk.models import CheckmkRewriteAttributeRule
from application.modules.checkmk.models import (
   CheckmkRuleMngmt,
   CheckmkBiRule,
   CheckmkBiAggregation,
   CheckmkDowntimeRule,
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
def export_tags(account):
    """
    Export Tags to Checkmk
    """
    try:
        details = []
        target_config = get_account_by_name(account)
        if target_config:
            rules = _load_rules()
            syncer = CheckmkTagSync()
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.config = target_config
            syncer.rewrite = rules['rewrite']
            syncer.export_tags()
            details.append(("info", "Succsessfull"))
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
    log.log(f"Export Tags to Checkmk Account: {target_config['name']}",
            source="Checkmk", details=details)

#.
#   .-- Export BI Rules
def export_bi_rules(account):
    """
    Export BI Rules to Checkmk
    """
    details = []
    try:
        target_config = get_account_by_name(account)
        if target_config:
            rules = _load_rules()
            syncer = SyncConfiguration()
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.config = target_config
            syncer.rewrite = rules['rewrite']

            actions = DefaultRule()
            actions.rules = CheckmkBiRule.objects(enabled=True)
            syncer.actions = actions
            syncer.export_bi_rules()
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        details.append(('error', f'CMK Error: {error_obj}'))
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
    log.log(f"Export BI Rules to Checkmk Account: {target_config['name']}",
            source="Checkmk", details=details)
#.
#   .-- Export BI Aggregations
def export_bi_aggregations(account):
    """
    Export BI Aggregations to Checkmk
    """
    details = []
    try:
        target_config = get_account_by_name(account)
        if target_config:
            rules = _load_rules()
            syncer = SyncConfiguration()
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.rewrite = rules['rewrite']
            syncer.config = target_config
            actions = DefaultRule()
            actions.rules = CheckmkBiAggregation.objects(enabled=True)
            syncer.actions = actions
            syncer.export_bi_aggregations()
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        details.append(('error', f'CMK Error: {error_obj}'))
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
    log.log(f"Export BI Aggregations to Checkmk Account: {target_config['name']}",
            source="Checkmk", details=details)

#.
#   .-- Inventorize Hosts


def inventorize_hosts(account):
    """
    Inventorize information from Checkmk Installation
    """
    config = get_account_by_name(account)
    inven = InventorizeHosts(account, config)
    inven.run()

#.
#   . -- Show missing hosts
def show_missing(account):
    """
    Return list of all currently missing hosts
    """
    config = get_account_by_name(account)
    cmk = CMK2()
    cmk.config = config

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
    account_config = get_account_by_name(account)
    if account_config['typ'] != 'cmkv2':
        print(f"{ColorCodes.FAIL} Not a Checkmk 2.x Account {ColorCodes.ENDC}")
        return False
    if "backery_key_id" not in account_config and "bakery_passphrase" not in account_config:
        print(f"{ColorCodes.FAIL} Please set baker_key_id and "\
              f"bakery_passphrase as Custom Account Config {ColorCodes.ENDC}")
        return False
    cmk = CMK2()
    cmk.config = account_config
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
    account_config = get_account_by_name(account)
    if account_config['typ'] != 'cmkv2':
        print(f"{ColorCodes.FAIL} Not a Checkmk 2.x Account {ColorCodes.ENDC}")
        return False
    cmk = CMK2()
    cmk.config = account_config
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
def export_groups(account, test_run=False):
    """
    Manage Groups in Checkmk
    """
    details = []
    try:
        target_config = get_account_by_name(account)
        if target_config:
            rules = _load_rules()
            syncer = SyncConfiguration()
            syncer.account = target_config['_id']
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.rewrite = rules['rewrite']
            syncer.config = target_config
            syncer.export_cmk_groups(test_run)
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
    log.log(f"Export Groups to Checkmk Account: {target_config['name']}",
            source="Checkmk", details=details)
#.
#   .-- Export Rules
def export_rules(account):
    """
    Create Rules in Checkmk
    """
    details = []
    try:
        target_config = get_account_by_name(account)
        if target_config:
            rules = _load_rules()
            syncer = SyncConfiguration()
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.config = target_config
            syncer.filter = rules['filter']

            syncer.rewrite = rules['rewrite']
            actions = CheckmkRulesetRule()
            actions.rules = CheckmkRuleMngmt.objects(enabled=True)
            syncer.actions = actions
            syncer.export_cmk_rules()
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
    log.log(f"Export Rules to Checkmk Account: {target_config['name']}",
            source="Checkmk", details=details)
#.
#    .-- Export Downtimes
def export_downtimes(account):
    """
    Create Rules in Checkmk
    """
    details = []
    try:
        target_config = get_account_by_name(account)
        if target_config:
            rules = _load_rules()
            syncer = CheckmkDowntimeSync()
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.config = target_config
            syncer.rewrite = rules['rewrite']

            actions = DefaultRule()
            actions.rules = CheckmkDowntimeRule.objects(enabled=True)
            syncer.actions = actions
            syncer.export_downtimes()
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
    log.log(f"Export Downtimes to Checkmk Account: {target_config['name']}",
            source="Checkmk", details=details)
#.
#   . Export Users
def export_users(account):
    """
    Export configured Users to Checkmk
    """
    details = []
    try:
        target_config = get_account_by_name(account)
        if target_config:
            syncer = SyncConfiguration()
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.config = target_config
            syncer.export_users()
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
        details.append(('error', f'CMK Error: {error_obj}'))
    log.log(f"Export Users to Checkmk Account: {target_config['name']}",
            source="Checkmk", details=details)
#.
