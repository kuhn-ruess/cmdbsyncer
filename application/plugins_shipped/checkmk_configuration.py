"""
Add Configuration in Checkmk
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get
import sys
import pprint
import re
import click
from application.modules.cmk2 import CMK2, cli_cmk, CmkException
from application.helpers.get_account import get_account_by_name
from application.helpers.debug import ColorCodes
from application.helpers.get_all_host_attributes import get_all_attributes
#from application.models.cmk_ruleset_rules import CmkRulesetRule
from application.models.cmk_group_rules import CmkGroupRule
from application.models.host import Host


#   .-- Command: Export Rulesets
#@cli_cmk.command('export_rules')
#def export_cmk_rules():
#    """WIP: Create Rules in Checkmk"""

#.
#   .-- Command: Export Group
@cli_cmk.command('export_groups')
@click.argument("account")
@click.option('-t', '--test-run', is_flag=True)
#pylint: disable=too-many-locals, too-many-branches
def export_cmk_groups(account, test_run):
    """Create Groups in Checkmk"""
    account_config = get_account_by_name(account)
    if account_config['typ'] != 'cmkv2':
        print(f"{ColorCodes.FAIL} Not a Checkmk 2.x Account {ColorCodes.ENDC}")
        sys.exit(1)
    cmk = CMK2(account_config)
    print(f"\n{ColorCodes.HEADER}Read Internal Configuration{ColorCodes.ENDC}")
    print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC} Read all Host Attributes")
    attributes = get_all_attributes()
    print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC} Read all Rules and group them")
    groups = {}
    replacers = [
      (',', ''),
      (' ', '_'),
    ]
    for rule in CmkGroupRule.objects(enabled=True):
        for outcome in rule.outcome:
            group_name = outcome.group_name
            groups.setdefault(group_name, [])
            regex = False
            if outcome.regex:
                regex = re.compile(outcome.regex)
            if outcome.foreach_type == 'value':
                for label_value in attributes.get(outcome.foreach):
                    if regex:
                        label_value = regex.findall(label_value)[0]
                    for needle, replacer in replacers:
                        label_value = label_value.replace(needle, replacer)
                    if label_value not in groups[group_name]:
                        groups[group_name].append(label_value)
            elif outcome.foreach_type == 'label':
                for label_key in [x for x,y in attributes.items() if outcome.foreach in y]:
                    if regex:
                        label_key = regex.findall(label_key)[0]
                    for needle, replacer in replacers:
                        label_key = label_key.replace(needle, replacer)
                    label_key = label_key.replace(' ', '_').strip()
                    if label_key not in groups[group_name]:
                        groups[group_name].append(label_key)

    print(f"\n{ColorCodes.HEADER}Start Sync{ColorCodes.ENDC}")
    account_id = account_config['_id']
    for group_type, configured_groups in groups.items():
        if group_type == "contact_groups":
            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Read Current Groups")
            url = "/domain-types/contact_group_config/collections/all"
            cmks_groups = cmk.request(url, method="GET")
            syncers_groups_in_cmk = []
            for cmk_group in [x['href'] for x in cmks_groups[0]['value']]:
                cmk_name = cmk_group.split('/')[-1]
                if cmk_name.startswith(f"cmdbsyncer_{account_id}_"):
                    syncers_groups_in_cmk.append(cmk_name)


            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Create Groups if needed")
            entries = []
            for group_alias in configured_groups:
                group_name = f"cmdbsyncer_{account_id}_{group_alias}"
                if group_name not in syncers_groups_in_cmk:
                    entries.append({
                        'alias' : group_alias,
                        'name' : group_name,
                    })
                print(f"{ColorCodes.OKBLUE}  *{ColorCodes.ENDC} Added {group_alias}")

            if entries:
                data = {
                    'entries': entries,
                }
                url = "/domain-types/contact_group_config/actions/bulk-create/invoke"
                if test_run:
                    print(f"\n{ColorCodes.HEADER}Output only (Testrun){ColorCodes.ENDC}")
                    pprint.pprint(entries)
                else:
                    print(f"\n{ColorCodes.HEADER}Send to Checkmk{ColorCodes.ENDC}")
                    cmk.request(url, data=data, method="POST")

            if not test_run:
                print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Delete Groups if needed")
                for group_alias in syncers_groups_in_cmk:
                    pure_alias = "_".join(group_alias.split('_')[2:])
                    if pure_alias not in configured_groups:
                        # Checkmk is not deleting objects if the still referenced
                        url = f"objects/contact_group_config/{group_alias}"
                        cmk.request(url, method="DELETE")
                        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Group {group_alias} deleted")



#.
#   .-- Command: Activate Changes
@cli_cmk.command('activate_changes')
@click.argument("account")
#pylint: disable=too-many-locals, too-many-branches
def activate_changes(account):
    """
    Activate Changes in given Instance
    """
    account_config = get_account_by_name(account)
    if account_config['typ'] != 'cmkv2':
        print(f"{ColorCodes.FAIL} Not a Checkmk 2.x Account {ColorCodes.ENDC}")
        sys.exit(1)
    cmk = CMK2(account_config)
    url = "/domain-types/activation_run/actions/activate-changes/invoke"
    data = {
        'redirect': False,
        'force_foreign_changes': True,
    }
    try:
        cmk.request(url, data=data, method="POST")
        print("Changes activated")
        sys.exit(0)
    except CmkException as errors:
        print(errors)
        sys.exit(1)




#.
#   .-- Command: Host Inventory
@cli_cmk.command('inventorize_hosts')
@click.argument('account')
#pylint: disable=too-many-locals
def run_cmk2_inventory(account):
    """
    Query CMK with Version  2.1p9 for Inventory Data
    """
    inventory_target = [
        'site', 'inventory_failed','is_offline','tag_agent',
    ]
    config = get_account_by_name(account)
    cmk = CMK2(config)

    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{account}{ColorCodes.ENDC}")


    print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting Config Data")
    url = "domain-types/host_config/collections/all?effective_attributes=true"
    api_hosts = cmk.request(url, method="GET")
    config_inventory = {}
    for host in api_hosts[0]['value']:
        hostname = host['id']
        attributes = host['extensions']['effective_attributes']
        host_inventory = {}
        for attribute in attributes:
            if attribute in inventory_target:
                host_inventory[f"cmk_{attribute}"] = attributes[attribute]

        config_inventory[hostname] = host_inventory


    # Inventory for Status Information
    url = "domain-types/service/collections/all"
    params={
        "query":
           '{"op": "or", "expr": ['\
           '{ "op": "=", "left": "description", "right": "Check_MK"}, '\
           '{ "op": "=", "left": "description", "right": "Check_MK Agent"},'\
           '{ "op": "=", "left": "description", "right": "Check_MK Discovery"}'\
           '] }',
        "columns":
           ['host_name', 'description', 'state', 'plugin_output'],
    }
    print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting Status Data")
    api_response = cmk.request(url, data=params, method="GET")
    status_inventory = {}
    for service in api_response[0]['value']:
        host_name = service['extensions']['host_name']
        service_description = service['extensions']['description'].lower().replace(' ', '_')
        service_state = service['extensions']['state']
        service_output = service['extensions']['plugin_output']
        status_inventory.setdefault(host_name, {})
        status_inventory[host_name][f"cmk_svc_{service_description}_state"] = service_state
        status_inventory[host_name][f"cmk_svc_{service_description}_output"] = service_output

    print(f"{ColorCodes.UNDERLINE}Write to DB{ColorCodes.ENDC}")

    for hostname in config_inventory:
        db_host = Host.get_host(hostname, False)
        if db_host:
            db_host.update_inventory('cmk_', config_inventory[hostname])
            db_host.update_inventory('cmk_svc)', status_inventory.get(hostname, {}))
            db_host.save()
            print(f" {ColorCodes.OKGREEN}* {ColorCodes.ENDC} Updated {hostname}")
        else:
            print(f" {ColorCodes.FAIL}* {ColorCodes.ENDC} Not in Syncer: {hostname}")
#.
