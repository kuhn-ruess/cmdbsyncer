"""
Add Configuration in Checkmk
"""
#pylint: disable=too-many-arguments, too-many-statements, consider-using-get, no-member
import sys
import re
import click
from application.modules.checkmk.cmk2 import CMK2, cli_cmk, CmkException
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes
from application.modules.checkmk.models import CheckmkGroupRule, CheckmkRuleMngmt
from application.models.host import Host

replacers = [
  (',', ''),
  (' ', '_'),
  ('/', '-'),
  ('&', '-'),
  ('(', '-'),
  (')', '-'),
  ('ü', 'ue'),
  ('ä', 'ae'),
  ('ö', 'oe'),
  ('ß', 'ss'),
]

def get_all_attributes():
    """
    Create dict with list of all possible attributes
    @ TODO: Honor Rewrites
    """
    collection_keys = {}
    collection_values = {}
    for host in Host.objects(available=True):
        for key, value in host.get_labels().items():
            # Add the Keys
            collection_keys.setdefault(key, [])
            if value not in collection_keys[key]:
                collection_keys[key].append(value)
            # Add the Values
            collection_values.setdefault(value, [])
            if key not in collection_values[value]:
                collection_values[value].append(key)

        for key, value in host.get_inventory().items():
            # Add the Keys
            collection_keys.setdefault(key, [])
            if value not in collection_keys[key]:
                collection_keys[key].append(value)

            # Add the Values
            collection_values.setdefault(value, [])
            if key not in collection_values[value]:
                collection_values[value].append(key)

    return collection_keys, collection_values

#   .-- Command: Export Rulesets
@cli_cmk.command('export_rules')
@click.argument("account")
def export_cmk_rules(account):
    """Create Rules in Checkmk"""
    account_config = get_account_by_name(account)
    account_id = account_config['_id']
    if not account_config or account_config['typ'] != 'cmkv2':
        print(f"{ColorCodes.FAIL} Not a Checkmk 2.x Account {ColorCodes.ENDC}")
        sys.exit(1)
    cmk = CMK2()
    cmk.config = account_config
    print(f"\n{ColorCodes.HEADER}Read Internal Configuration{ColorCodes.ENDC}")
    print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC} Read all Host Attributes")
    attributes = get_all_attributes()
    print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC} Read all Rules and group them")
    groups = {}
    prefixes = {
        'host_contactgroups': f'cmdbsyncer_cg_{account_id}_',
        'host_groups': f'cmdbsyncer_hg_{account_id}_'
    }
    for rule in CheckmkRuleMngmt.objects(enabled=True):
        outcome = rule.outcome
        cmk_group_name = rule.rule_group
        groups.setdefault(cmk_group_name, [])
        regex = re.compile(outcome.regex)
        prefix = ''
        if outcome.group_created_by_syncer:
            prefix = prefixes[cmk_group_name]
        if outcome.foreach_type == 'value':
            for label_value in attributes[0].get(outcome.foreach, []):
                label_value = regex.findall(label_value)[0]
                for needle, replacer in replacers:
                    label_value = label_value.replace(needle, replacer).strip()
                group_name = prefix + outcome.template_group.replace('$1', label_value)
                label_data = outcome.template_label.replace('$1', label_value)
                if (group_name, label_data)  not in groups[cmk_group_name]:
                    groups[cmk_group_name].append((group_name, label_data))
        elif outcome.foreach_type == 'label':
            for label_key in [x for x,y in attributes[1].items() if outcome.foreach in y]:
                label_key = regex.findall(label_key)[0]
                for needle, replacer in replacers:
                    label_key = label_key.replace(needle, replacer).strip()
                label_key = label_key.replace(' ', '_').strip()
                group_name = prefix + outcome.template_group.replace('$1', label_key)
                label_data = outcome.template_label.replace('$1', label_key)
                if (group_name, label_data) not in groups[cmk_group_name]:
                    groups[cmk_group_name].append((group_name, label_data))

    print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC} Clean existing CMK configuration")
    for cmk_group_name in prefixes.keys():
        url = f"domain-types/rule/collections/all?ruleset_name={cmk_group_name}"
        rule_response = cmk.request(url, method="GET")[0]
        for rule in rule_response['value']:
            if rule['extensions']['properties']['description'] != \
                f'cmdbsyncer_{account_id}':
                continue
            group_name = rule['extensions']['value_raw']
            condition = rule['extensions']['conditions']['host_labels'][0]
            label_data = f"{condition['key']}:{condition['value']}"
            # Replace needed since response from cmk is "'groupname'"
            search_group = (group_name.replace("'",""), label_data)
            if search_group not in groups.get(cmk_group_name, []):
                rule_id = rule['id']
                print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} DELETE Rule in {cmk_group_name} {rule_id}")
                url = f'/objects/rule/{rule_id}'
                cmk.request(url, method="DELETE")
            else:
                # In This case we don't need to create it
                groups[cmk_group_name].remove(search_group)


    print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC} Create new Rules")
    for cmk_group_name, rules in groups.items():
        for group_name, label_data in rules:
            label_key, label_value = label_data.split(':')
            if not label_value:
                continue
            template = {
                "ruleset": f"{cmk_group_name}",
                "folder": "/",
                "properties": {
                    "disabled": False,
                    "description": f"cmdbsyncer_{account_id}"
                },
                "value_raw": f"'{group_name}'",
                "conditions": {
                    "host_tags": [],
                    "host_labels": [
                        {
                            "key": label_key,
                            "operator": "is",
                            "value": label_value
                        }
                    ],
                }
            }

            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Create Rule in {cmk_group_name} ({label_key}:{label_value} = {group_name})")
            url = "domain-types/rule/collections/all"
            try:
                cmk.request(url, data=template, method="POST")
            except CmkException as error:
                print(f"{ColorCodes.FAIL} Failue: {error} {ColorCodes.ENDC}")
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
    cmk = CMK2()
    cmk.config = account_config
    print(f"\n{ColorCodes.HEADER}Read Internal Configuration{ColorCodes.ENDC}")
    print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC} Read all Host Attributes")
    attributes = get_all_attributes()
    print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC} Read all Rules and group them")
    groups = {}
    for rule in CheckmkGroupRule.objects(enabled=True):
        outcome = rule.outcome
        group_name = outcome.group_name
        groups.setdefault(group_name, [])
        regex = False
        if outcome.regex:
            regex = re.compile(outcome.regex)
        if outcome.foreach_type == 'value':
            for label_value in attributes[0].get(outcome.foreach, []):
                if regex:
                    label_value = regex.findall(label_value)[0]
                for needle, replacer in replacers:
                    label_value = label_value.replace(needle, replacer).strip()
                if label_value and label_value not in groups[group_name]:
                    groups[group_name].append(label_value)
        elif outcome.foreach_type == 'label':
            for label_key in [x for x,y in attributes[1].items() if outcome.foreach in y]:
                if regex:
                    label_key = regex.findall(label_key)[0]
                for needle, replacer in replacers:
                    label_key = label_key.replace(needle, replacer).strip()
                label_key = label_key.replace(' ', '_').strip()
                if label_key and label_key not in groups[group_name]:
                    groups[group_name].append(label_key)

    print(f"\n{ColorCodes.HEADER}Start Sync{ColorCodes.ENDC}")
    account_id = account_config['_id']
    urls = {
        'contact_groups': {
            'short': "cg",
            'get': "/domain-types/contact_group_config/collections/all",
            'put': "/domain-types/contact_group_config/actions/bulk-create/invoke",
            'delete': "/objects/contact_group_config/"
        },
        'host_groups' : {
            'short': "hg",
            'get': "/domain-types/host_group_config/collections/all",
            'put': "/domain-types/host_group_config/actions/bulk-create/invoke",
            'delete': "/objects/host_group_config/"
        },
        'service_groups' : {
            'short': "sg",
            'get': "/domain-types/service_group_config/collections/all",
            'put': "/domain-types/service_group_config/actions/bulk-create/invoke",
            'delete': "/objects/service_group_config/"
        },
    }
    for group_type, configured_groups in groups.items():
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Read Current {group_type}")
        url = urls[group_type]['get']
        short = urls[group_type]['short']
        cmks_groups = cmk.request(url, method="GET")
        syncers_groups_in_cmk = []
        name_prefix = f"cmdbsyncer_{short}_{account_id}_"
        for cmk_group in [x['href'] for x in cmks_groups[0]['value']]:
            cmk_name = cmk_group.split('/')[-1]
            if cmk_name.startswith(name_prefix):
                syncers_groups_in_cmk.append(cmk_name)


        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Create {group_type}s if needed")
        entries = []
        new_group_names = []
        for new_group_alias in configured_groups:
            new_group_name = f"{name_prefix}{new_group_alias}"
            new_group_names.append(new_group_name)
            if new_group_name not in syncers_groups_in_cmk:
                print(f"{ColorCodes.OKBLUE}  *{ColorCodes.ENDC} Added {new_group_alias}")
                entries.append({
                    'alias' : short+new_group_alias,
                    'name' : new_group_name,
                })

        if entries:
            data = {
                'entries': entries,
            }
            url = urls[group_type]['put']
            if test_run:
                print(f"\n{ColorCodes.HEADER}Output only (Testrun){ColorCodes.ENDC}")
            else:
                print(f"\n{ColorCodes.HEADER}Send {group_type} to Checkmk{ColorCodes.ENDC}")
                try:
                    cmk.request(url, data=data, method="POST")
                except CmkException as error:
                    print(f"{ColorCodes.FAIL} {error} {ColorCodes.ENDC}")
                    return


        if not test_run:
            print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Delete Groups if needed")
            for group_alias in syncers_groups_in_cmk:
                if group_alias not in new_group_names:
                    # Checkmk is not deleting objects if the still referenced
                    url = f"{urls[group_type]['delete']}{group_alias}"
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
    cmk = CMK2()
    cmk.config = account_config
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
#   .-- Command: Bake and Sign agents
@cli_cmk.command('bake_and_sign_agents')
@click.argument("account")
#pylint: disable=too-many-locals, too-many-branches
def bake_and_sign(account):
    """
    Bake and Sign Agents for Instance
    """
    account_config = get_account_by_name(account)
    custom_config = {x['name']:x['value'] for x in account_config['custom_fields']}
    if account_config['typ'] != 'cmkv2':
        print(f"{ColorCodes.FAIL} Not a Checkmk 2.x Account {ColorCodes.ENDC}")
        sys.exit(1)
    if not "backery_key_id" in custom_config and not "bakery_passphrase" in custom_config:
        print(f"{ColorCodes.FAIL} Please set baker_key_id and "\
              f"bakery_passphrase as Custom Account Config {ColorCodes.ENDC}")
        sys.exit(1)
    cmk = CMK2()
    cmk.config = account_config
    url = "/domain-types/agent/actions/bake_and_sign/invoke"
    data = {
        'key_id': int(custom_config['bakery_key_id']),
        'passphrase': custom_config['bakery_passphrase'],
    }
    try:
        cmk.request(url, data=data, method="POST")
        print("Signed and Baked Agents")
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
    cmk = CMK2()
    cmk.config = config

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
