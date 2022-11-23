"""
Checkmk Configuration
"""
#pylint: disable=import-error, too-many-locals, too-many-branches, too-many-statements
import re
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.checkmk.models import CheckmkGroupRule, CheckmkRuleMngmt
from application.modules.debug import ColorCodes as CC
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

class SyncConfiguration(CMK2):
    """
    Sync jobs for Checkmk Config
    """

    def parse_attributes(self):
        """
        Create dict with list of all possible attributes
        """
        collection_keys = {}
        collection_values = {}
        for db_host in Host.objects(available=True):
            if attributes := self.get_host_attributes(db_host):
                for key, value in attributes['all'].items():
                    # Add the Keys
                    collection_keys.setdefault(key, [])
                    if value not in collection_keys[key]:
                        collection_keys[key].append(value)
                    # Add the Values
                    collection_values.setdefault(value, [])
                    if key not in collection_values[value]:
                        collection_values[value].append(key)

        return collection_keys, collection_values

#   .-- Export Rulesets
    def export_cmk_rules(self):
        """
        Export config rules to checkmk
        """

        print(f"\n{CC.HEADER}Read Internal Configuration{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Read all Host Attributes")
        attributes = self.parse_attributes()
        print(f"{CC.OKGREEN} -- {CC.ENDC} Read all Rules and group them")
        groups = {}
        prefixes = {
            'host_contactgroups': f'cmdbsyncer_cg_{self.account_id}_',
            'host_groups': f'cmdbsyncer_hg_{self.account_id}_'
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
                for label_value in attributes[1].get(outcome.foreach, []):
                    label_value = regex.findall(label_value)[0]
                    for needle, replacer in replacers:
                        label_value = label_value.replace(needle, replacer).strip()
                    group_name = prefix + outcome.template_group.replace('$1', label_value)
                    label_data = outcome.template_label.replace('$1', label_value)
                    if (group_name, label_data)  not in groups[cmk_group_name]:
                        groups[cmk_group_name].append((group_name, label_data))
            elif outcome.foreach_type == 'label':
                for label_key in [x for x,y in attributes[0].items() if outcome.foreach in y]:
                    label_key = regex.findall(label_key)[0]
                    for needle, replacer in replacers:
                        label_key = label_key.replace(needle, replacer).strip()
                    label_key = label_key.replace(' ', '_').strip()
                    group_name = prefix + outcome.template_group.replace('$1', label_key)
                    label_data = outcome.template_label.replace('$1', label_key)
                    if (group_name, label_data) not in groups[cmk_group_name]:
                        groups[cmk_group_name].append((group_name, label_data))

        print(f"{CC.OKGREEN} -- {CC.ENDC} Clean existing CMK configuration")
        for cmk_group_name in prefixes:
            url = f"domain-types/rule/collections/all?ruleset_name={cmk_group_name}"
            rule_response = self.request(url, method="GET")[0]
            for rule in rule_response['value']:
                if rule['extensions']['properties']['description'] != \
                    f'cmdbsyncer_{self.account_id}':
                    continue
                group_name = rule['extensions']['value_raw']
                condition = rule['extensions']['conditions']['host_labels'][0]
                label_data = f"{condition['key']}:{condition['value']}"
                # Replace needed since response from cmk is "'groupname'"
                search_group = (group_name.replace("'",""), label_data)
                if search_group not in groups.get(cmk_group_name, []):
                    rule_id = rule['id']
                    print(f"{CC.OKBLUE} *{CC.ENDC} DELETE Rule in {cmk_group_name} {rule_id}")
                    url = f'/objects/rule/{rule_id}'
                    self.request(url, method="DELETE")
                else:
                    # In This case we don't need to create it
                    groups[cmk_group_name].remove(search_group)


        print(f"{CC.OKGREEN} -- {CC.ENDC} Create new Rules")
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
                        "description": f"cmdbsyncer_{self.account_id}"
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

                print(f"{CC.OKBLUE} *{CC.ENDC} Create Rule in {cmk_group_name} " \
                      f"({label_key}:{label_value} = {group_name})")
                url = "domain-types/rule/collections/all"
                try:
                    self.request(url, data=template, method="POST")
                except CmkException as error:
                    print(f"{CC.FAIL} Failue: {error} {CC.ENDC}")
#.
#   .-- Export Group

    def export_cmk_groups(self, test_run):
        """
        Export all Checkmk Groups
        """
        print(f"\n{CC.HEADER}Read Internal Configuration{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Read all Host Attributes")
        attributes = self.parse_attributes()
        print(f"{CC.OKGREEN} -- {CC.ENDC} Read all Rules and group them")
        groups = {}
        for rule in CheckmkGroupRule.objects(enabled=True):
            outcome = rule.outcome
            group_name = outcome.group_name
            groups.setdefault(group_name, [])
            regex_match = False
            if outcome.regex:
                regex_match = re.compile(outcome.regex)
            if outcome.foreach_type == 'value':
                for label_value in attributes[1].get(outcome.foreach, []):
                    if regex_match:
                        label_value = regex_match.findall(label_value)[0]
                    for needle, replacer in replacers:
                        label_value = label_value.replace(needle, replacer).strip()
                    if label_value and label_value not in groups[group_name]:
                        groups[group_name].append(label_value)
            elif outcome.foreach_type == 'label':
                for label_key in [x for x,y in attributes[0].items() if outcome.foreach in y]:
                    if regex_match:
                        label_key = regex_match.findall(label_key)[0]
                    for needle, replacer in replacers:
                        label_key = label_key.replace(needle, replacer).strip()
                    label_key = label_key.replace(' ', '_').strip()
                    if label_key and label_key not in groups[group_name]:
                        groups[group_name].append(label_key)

        print(f"\n{CC.HEADER}Start Sync{CC.ENDC}")
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
            print(f"{CC.OKBLUE} *{CC.ENDC} Read Current {group_type}")
            url = urls[group_type]['get']
            short = urls[group_type]['short']
            cmks_groups = self.request(url, method="GET")
            syncers_groups_in_cmk = []
            name_prefix = f"cmdbsyncer_{short}_{self.account_id}_"
            for cmk_group in [x['href'] for x in cmks_groups[0]['value']]:
                cmk_name = cmk_group.split('/')[-1]
                if cmk_name.startswith(name_prefix):
                    syncers_groups_in_cmk.append(cmk_name)


            print(f"{CC.OKBLUE} *{CC.ENDC} Create {group_type}s if needed")
            entries = []
            new_group_names = []
            for new_group_alias in configured_groups:
                new_group_name = f"{name_prefix}{new_group_alias}"
                new_group_names.append(new_group_name)
                if new_group_name not in syncers_groups_in_cmk:
                    print(f"{CC.OKBLUE}  *{CC.ENDC} Added {new_group_alias}")
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
                    print(f"\n{CC.HEADER}Output only (Testrun){CC.ENDC}")
                else:
                    print(f"\n{CC.HEADER}Send {group_type} to Checkmk{CC.ENDC}")
                    try:
                        self.request(url, data=data, method="POST")
                    except CmkException as error:
                        print(f"{CC.FAIL} {error} {CC.ENDC}")
                        return


            if not test_run:
                print(f"{CC.OKBLUE} *{CC.ENDC} Delete Groups if needed")
                for group_alias in syncers_groups_in_cmk:
                    if group_alias not in new_group_names:
                        # Checkmk is not deleting objects if the still referenced
                        url = f"{urls[group_type]['delete']}{group_alias}"
                        self.request(url, method="DELETE")
                        print(f"{CC.OKBLUE} *{CC.ENDC} Group {group_alias} deleted")

#.
