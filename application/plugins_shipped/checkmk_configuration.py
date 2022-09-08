"""
Add Configuration in Checkmk
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get
import sys
import click
from application.modules.cmk2 import CMK2, cli_cmk
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
#pylint: disable=too-many-locals, too-many-branches
def export_cmk_groups(account):
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
    for rule in CmkGroupRule.objects(enabled=True):
        for outcome in rule.outcome:
            group_name = outcome.group_name
            groups.setdefault(group_name, [])
            for label_value in attributes.get(outcome.foreach_label):
                if label_value not in groups[group_name]:
                    groups[group_name].append(label_value)

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

            if entries:
                data = {
                    'entries': entries,
                }
                url = "/domain-types/contact_group_config/actions/bulk-create/invoke"
                cmk.request(url, data=data, method="POST")

            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Delete Groups if needed")
            for group_alias in syncers_groups_in_cmk:
                pure_alias = "_".join(group_alias.split('_')[2:])
                if pure_alias not in configured_groups:
                    # Checkmk is not deleting objects if the still referenced
                    url = f"objects/contact_group_config/{group_alias}"
                    cmk.request(url, method="DELETE")






#.
#   .-- Command: Host Inventory
@cli_cmk.command('hosts_inventory')
@click.argument('account')
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


    url = "domain-types/host_config/collections/all?effective_attributes=true"
    api_hosts = cmk.request(url, method="GET")
    for host in api_hosts[0]['value']:
        hostname = host['id']
        attributes = host['extensions']['effective_attributes']
        host_inventory = {}
        for attribute in attributes:
            if attribute in inventory_target:
                host_inventory[f"cmk_{attribute}"] = attributes[attribute]

        db_host = Host.get_host(hostname, False)
        if db_host:
            db_host.inventory = host_inventory
            db_host.save()
            print(f" {ColorCodes.OKGREEN}* {ColorCodes.ENDC} Updated {hostname}")
        else:
            print(f" {ColorCodes.FAIL}* {ColorCodes.ENDC} Hot in Syncer: {hostname}")
#.
