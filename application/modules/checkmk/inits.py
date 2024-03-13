"""
#pylint: disable=too-many-locals
Inits for the Plugins
"""
#pylint: disable=too-many-locals, too-many-nested-blocks
import base64
import ast
import json
from application.helpers.get_account import get_account_by_name
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes
from application.models.host import Host
from application.modules.checkmk.config_sync import SyncConfiguration
from application.modules.checkmk.rules import CheckmkRulesetRule, DefaultRule
from application.modules.checkmk.models import (
   CheckmkRuleMngmt,
   CheckmkBiRule,
   CheckmkBiAggregation,
   CheckmkInventorizeAttributes
)
from application.plugins.checkmk import _load_rules


#   .-- Export Tags
def export_tags(account):
    """
    Export Tags to Checkmk
    """
    try:
        target_config = get_account_by_name(account)
        if target_config:
            syncer = SyncConfiguration()
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.config = target_config
            syncer.export_tags()
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')

#.

#   .-- Export BI Rules
def export_bi_rules(account):
    """
    Export BI Rules to Checkmk
    """
    try:
        target_config = get_account_by_name(account)
        if target_config:
            syncer = SyncConfiguration()
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.config = target_config
            actions = DefaultRule()
            actions.rules = CheckmkBiRule.objects(enabled=True)
            syncer.actions = actions
            syncer.export_bi_rules()
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
#.
#   .-- Export BI Aggregations
def export_bi_aggregations(account):
    """
    Export BI Aggregations to Checkmk
    """
    try:
        target_config = get_account_by_name(account)
        if target_config:
            syncer = SyncConfiguration()
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.config = target_config
            actions = DefaultRule()
            actions.rules = CheckmkBiAggregation.objects(enabled=True)
            syncer.actions = actions
            syncer.export_bi_aggregations()
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')

#.
#   .-- Inventorize Hosts

def add_host(host, found_hosts):
    """
    Just add if not in
    """
    if host not in found_hosts:
        found_hosts.append(host)
    return found_hosts

def inventorize_hosts(account):
    """
    Inventorize information from Checkmk Installation
    """

    fields = {}

    for rule in CheckmkInventorizeAttributes.objects():
        fields.setdefault(rule.attribute_source, [])
        field_list = [x.strip() for x in rule.attribute_names.split(',')]
        fields[rule.attribute_source] += field_list

    config = get_account_by_name(account)
    cmk = CMK2()
    cmk.config = config


    # Check if Rules are set,
    # If not, abort to prevent loss of data
    if not fields:
        raise CmkException("No Inventory Rules configured")



    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{account}{ColorCodes.ENDC}")

    found_hosts = []


    # Inventory for Status Information
    print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting Status Data")
    url = "domain-types/service/collections/all"

    columns = ['host_name', 'description', 'state', 'plugin_output', 'host_labels']

    if fields.get('cmk_inventory'):
        columns.append('host_mk_inventory')
    if fields.get('cmk_services'):
        expr = []
        for field in fields['cmk_services']:
            expr.append({"op": "=", "left": "description", "right": field})

        query = {
            "op": "or",
            "expr": expr,
        }
        params={
            "query": str(json.dumps(query)),
            "columns": columns
        }
    else:
        params={
            "query":
               '{ "op": "=", "left": "description", "right": "Check_MK"}',
            "columns": columns
        }

    api_response = cmk.request(url, data=params, method="GET")
    status_inventory = {}
    label_inventory = {}
    service_label_inventory = {}
    hw_sw_inventory = {}
    for service in api_response[0]['value']:
        hostname = service['extensions']['host_name']
        add_host(hostname, found_hosts)
        service_description = service['extensions']['description'].lower().replace(' ', '_')
        service_state = service['extensions']['state']
        service_output = service['extensions']['plugin_output']
        labels = service['extensions']['host_labels']
        status_inventory.setdefault(hostname, {})
        label_inventory.setdefault(hostname, {})
        for label, label_value in labels.items():
            label_inventory[hostname][label] = label_value
        if fields.get('cmk_inventory'):
            hw_sw_inventory.setdefault(hostname, {})
            raw_inventory = service['extensions']['host_mk_inventory']['value'].encode('ascii')
            raw_decoded_inventory = base64.b64decode(raw_inventory).decode('utf-8')

            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Parsing HW/SW Inventory Data")
            inv_data = ast.literal_eval(raw_decoded_inventory)
            for field in fields['cmk_inventory']:
                paths = field.split('.')
                if len(paths) == 1:
                    inv_pairs = inv_data['Nodes'][paths[0]]['Attributes']['Pairs']

                elif len(paths) == 2:
                    try:
                        inv_pairs = \
                            inv_data['Nodes'][paths[0]]['Nodes'][paths[1]]['Attributes']['Pairs']


                    except KeyError:
                        inv_pairs = \
                            inv_data['Nodes'][paths[0]]['Nodes'][paths[1]]['Table']['Rows']


                if isinstance(inv_pairs, dict):
                    for key, value in inv_pairs.items():
                        hw_sw_inventory[hostname][f'{paths[0]}__{key}'] = value
                elif isinstance(inv_pairs, list):
                    hw_sw_inventory[hostname][f'{paths[0]}__{paths[1]}'] = inv_pairs

        status_inventory[hostname][f"{service_description}_state"] = service_state
        status_inventory[hostname][f"{service_description}_output"] = service_output


    if fields.get('cmk_service_labels'):
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting Service Labels")
        columns = ['host_name','label_names', 'label_values']
        expr = []
        for field in fields['cmk_service_labels']:
            expr.append({"op": "~", "left": "description", "right": field})
        query = {
            "op": "or",
            "expr": expr,
        }
        params={
            "query": str(json.dumps(query)),
            "columns": columns
        }
        api_response = cmk.request(url, data=params, method="GET")
        for service in api_response[0]['value']:
            names = service['extensions']['label_names']
            values = service['extensions']['label_values']
            if not names:
                continue
            names = service['extensions']['label_names']
            values = service['extensions']['label_values']
            service_labels = zip(names, values)
            hostname = service['extensions']['host_name']
            add_host(hostname, found_hosts)
            service_label_inventory.setdefault(hostname, {})
            for name, value in service_labels:
                service_label_inventory[hostname][name] = value

    config_inventory = {}
    if fields.get('cmk_attributes') or fields.get('cmk_labels'):
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting Config Data")
        url = "domain-types/host_config/collections/all?effective_attributes=true"
        api_hosts = cmk.request(url, method="GET")
        for host in api_hosts[0]['value']:
            hostname = host['id']
            add_host(hostname, found_hosts)
            attributes = host['extensions']
            attributes.update(host['extensions']['effective_attributes'])

            host_inventory = {}

            if fields.get('cmk_attributes'):
                for attribute_key, attribute_value in attributes.items():
                    if attribute_key in fields['cmk_attributes']:
                        host_inventory[attribute_key] = attribute_value
                for search in fields['cmk_attributes']:
                    if search.endswith('*'):
                        needle = search[:-1]
                        for attribute_key, attribute_value in attributes.items():
                            if attribute_key.startswith(needle):
                                host_inventory[attribute_key] = attribute_value

            if fields.get('cmk_labels'):
                labels = label_inventory.get(hostname, {})
                labels.update(attributes['labels'])
                for label_key, label_value in labels.items():
                    if label_key in fields['cmk_labels']:
                        label_key = label_key.replace('cmk/','')
                        host_inventory['label_'+label_key] = label_value

                for search in fields['cmk_labels']:
                    if search.endswith('*'):
                        needle = search[:-1]
                        for label in labels.keys():
                            if label.startswith(needle):
                                label_name = label.replace('cmk/','')
                                host_inventory['label_'+label_name] = labels[label]

            config_inventory[hostname] = host_inventory




    print(f"{ColorCodes.UNDERLINE}Write to DB{ColorCodes.ENDC}")

    # pylint: disable=consider-using-dict-items
    for hostname in found_hosts:
        db_host = Host.get_host(hostname, False)
        if db_host:
            db_host.update_inventory('cmk', config_inventory[hostname])
            db_host.update_inventory('cmk_svc', status_inventory.get(hostname, {}))
            db_host.update_inventory('cmk_svc_labels', service_label_inventory.get(hostname, {}))
            db_host.update_inventory('cmk_hw_sw_inv', hw_sw_inventory.get(hostname, {}))
            db_host.save()
            print(f" {ColorCodes.OKGREEN}* {ColorCodes.ENDC} Updated {hostname}")
        else:
            print(f" {ColorCodes.FAIL}* {ColorCodes.ENDC} Not in Syncer: {hostname}")
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
    try:
        target_config = get_account_by_name(account)
        if target_config:
            syncer = SyncConfiguration()
            syncer.account = target_config['_id']
            syncer.account_id = str(target_config['_id'])
            syncer.account_name = target_config['name']
            syncer.config = target_config
            syncer.export_cmk_groups(test_run)
        else:
            print(f"{ColorCodes.FAIL} Config not found {ColorCodes.ENDC}")
    except CmkException as error_obj:
        print(f'C{ColorCodes.FAIL}MK Connection Error: {error_obj} {ColorCodes.ENDC}')
#.
#   .-- Export Rules
def export_rules(account):
    """
    Create Rules in Checkmk
    """
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
#.
#   . Export Users
def export_users(account):
    """
    Export configured Users to Checkmk
    """
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
#.
