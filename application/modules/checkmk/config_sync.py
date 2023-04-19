"""
Checkmk Configuration
"""
#pylint: disable=import-error, too-many-locals, too-many-branches, too-many-statements, no-member
import re
import ast
import jinja2
from mongoengine.errors import DoesNotExist
from application import log
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.checkmk.models import CheckmkGroupRule, CheckmkObjectCache
from application.modules.debug import ColorCodes as CC
from application.models.host import Host

replacers = [
  (' ', '_'),
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

    @staticmethod
    def replace(input_raw):
        """
        Replace all given inputs
        """
        input_str = str(input_raw)
        for needle, replacer in replacers:
            input_str = input_str.replace(needle, replacer)
        return input_str.strip()

    def get_cache_object(self, group):
        """
        Get Cache Objects
        """
        try:
            return CheckmkObjectCache.objects.get(cache_group=group, account=self.account)
        except DoesNotExist:
            new = CheckmkObjectCache()
            new.cache_group = group
            new.account = self.account
            return new

    def parse_attributes(self):
        """
        Create dict with list of all possible attributes
        """
        collection_keys = {}
        collection_values = {}
        for db_host in Host.objects(available=True):
            if attributes := self.get_host_attributes(db_host, 'cmk_conf'):
                for key, value in attributes['all'].items():
                    # Add the Keys
                    collection_keys.setdefault(key, [])
                    if value not in collection_keys[key]:
                        collection_keys[key].append(value)
                    # Add the Values
                    collection_values.setdefault(value, [])
                    if key not in collection_values[value]:
                        collection_values[value].append(key)
        # [0] All Values behind Label
        # [1] All Keys which have value
        return collection_keys, collection_values

#   .-- Export Rulesets
    def export_cmk_rules(self):
        """
        Export config rules to checkmk
        """
        messages = []
        print(f"\n{CC.HEADER}Build needed Rules{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")

        rulsets_by_type = {}

        for db_host in Host.objects(available=True):
            attributes = self.get_host_attributes(db_host, 'cmk_conf')
            if not attributes:
                continue
            host_actions = self.actions.get_outcomes(db_host, attributes['all'])
            if host_actions:
                for rule_type, rules in host_actions.items():
                    for rule_params in rules:
                        # Render Template Value
                        condition_tpl = {"host_tags": [], "service_labels": []}
                        value_tpl = jinja2.Template(rule_params['value_template'])
                        value = \
                            value_tpl.render(HOSTNAME=db_host.hostname, **attributes['all'])

                        if rule_params['condition_label_template']:
                            label_condition_tpl = \
                                jinja2.Template(rule_params['condition_label_template'])
                            label_condition = \
                                label_condition_tpl.render(HOSTNAME=db_host.hostname, \
                                                                **attributes['all'])

                            label_key, label_value = label_condition.split(':')
                            # Fix bug in case of empty Labels in store
                            if not label_key and not label_value:
                                continue
                            condition_tpl['host_labels'] = [{
                                                    "key": label_key,
                                                    "operator": "is",
                                                    "value": label_value
                                                 }]
                        del rule_params['condition_label_template']

                        if rule_params['condition_host']:
                            host_condition_tpl = \
                                jinja2.Template(rule_params['condition_host'])

                            host_condition = \
                                host_condition_tpl.render(HOSTNAME=db_host.hostname, \
                                                                **attributes['all'])
                            if host_condition:
                                condition_tpl["host_name"]= {
                                                "match_on": host_condition.split(','),
                                                "operator": "one_of"
                                              }

                        del rule_params['condition_host']

                        # Overwrite the Params again
                        rule_params['value'] = value
                        del rule_params['value_template']

                        rule_params['condition'] = condition_tpl

                        rulsets_by_type.setdefault(rule_type, [])
                        if rule_params not in rulsets_by_type[rule_type]:
                            rulsets_by_type[rule_type].append(rule_params)

        print(f"{CC.OKGREEN} -- {CC.ENDC} Clean existing CMK configuration")
        for ruleset_name, rules in rulsets_by_type.items():
            url = f"domain-types/rule/collections/all?ruleset_name={ruleset_name}"
            rule_response = self.request(url, method="GET")[0]
            for cmk_rule in rule_response['value']:
                if cmk_rule['extensions']['properties'].get('description', '') != \
                    f'cmdbsyncer_{self.account_id}':
                    continue



                value = cmk_rule['extensions']['value_raw']
                cmk_condition = cmk_rule['extensions']['conditions']
                rule_found = False
                for rule in rules:
                    cmk_value = ast.literal_eval(rule['value'])
                    check_value = ast.literal_eval(value)
                    if rule['condition'] == cmk_condition and cmk_value == check_value:
                        rule_found = True
                        # Remove from list, so that it not will be created in the next step
                        rulsets_by_type[ruleset_name].remove(rule)

                if not rule_found: # Not existing any more
                    rule_id = cmk_rule['id']
                    print(f"{CC.OKBLUE} *{CC.ENDC} DELETE Rule in {ruleset_name} {rule_id}")
                    url = f'/objects/rule/{rule_id}'
                    self.request(url, method="DELETE")
                    messages.append(("INFO", f"Deleted Rule in {ruleset_name} {rule_id}"))

        print(f"{CC.OKGREEN} -- {CC.ENDC} Create new Rules")
        for ruleset_name, rules in rulsets_by_type.items():
            for rule in rules:
                template = {
                    "ruleset": f"{ruleset_name}",
                    "folder": rule['folder'],
                    "properties": {
                        "disabled": False,
                        "description": f"cmdbsyncer_{self.account_id}",
                        "comment": rule['comment'],
                    },
                    'conditions' : rule['condition'],
                    "value_raw": rule['value'],
                }


                print(f"{CC.OKBLUE} *{CC.ENDC} Create Rule in {ruleset_name} " \
                      f"({rule['condition']})")
                url = "domain-types/rule/collections/all"
                try:
                    self.request(url, data=template, method="POST")
                    messages.append(("INFO", f"Created Rule in {ruleset_name}: {rule['value']}"))
                except CmkException as error:
                    print(f"{CC.FAIL} Failue: {error} {CC.ENDC}")

        log.log(f"Checkmk Rules synced with {self.account_name}", \
                        source="CMK_RULE_SYNC", details=messages)
#.
#   .-- Export Group

    def export_cmk_groups(self, test_run):
        """
        Export all Checkmk Groups
        """
        messages = []
        print(f"\n{CC.HEADER}Read Internal Configuration{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Read all Host Attributes")
        attributes = self.parse_attributes()
        print(f"{CC.OKGREEN} -- {CC.ENDC} Read all Rules and group them")
        groups = {}
        for rule in CheckmkGroupRule.objects(enabled=True):
            outcome = rule.outcome
            group_name = outcome.group_name
            groups.setdefault(group_name, [])
            rewrite = False
            if outcome.rewrite:
                rewrite = True
                rewrite_tpl = jinja2.Template(outcome.rewrite)
            if outcome.foreach_type == 'value':
                for label_value in attributes[1].get(outcome.foreach, []):
                    if rewrite:
                        label_value = rewrite_tpl.render(name=label_value)
                    label_value = self.replace(label_value)
                    if label_value and label_value not in groups[group_name]:
                        groups[group_name].append(label_value)
            elif outcome.foreach_type == 'label':
                print("Check for label:")
                for label_key in attributes[0].get(outcome.foreach, []):
                    print(f"Checking: {label_key}")
                    if rewrite:
                        label_key = rewrite_tpl.render(name=label_key)
                    label_key = self.replace(label_key)
                    label_key = label_key.replace(' ', '_').strip()
                    if label_key and label_key not in groups[group_name]:
                        groups[group_name].append(label_key)

        print(f"\n{CC.HEADER}Start Sync{CC.ENDC}")
        urls = {
            'contact_groups': {
                'get': "/domain-types/contact_group_config/collections/all",
                'put': "/domain-types/contact_group_config/actions/bulk-create/invoke",
                'delete': "/objects/contact_group_config/"
            },
            'host_groups' : {
                'get': "/domain-types/host_group_config/collections/all",
                'put': "/domain-types/host_group_config/actions/bulk-create/invoke",
                'delete': "/objects/host_group_config/"
            },
            'service_groups' : {
                'get': "/domain-types/service_group_config/collections/all",
                'put': "/domain-types/service_group_config/actions/bulk-create/invoke",
                'delete': "/objects/service_group_config/"
            },
        }
        for group_type, configured_groups in groups.items():
            print(f"{CC.OKBLUE} *{CC.ENDC} Read Current {group_type}")
            url = urls[group_type]['get']

            cmks_groups = self.request(url, method="GET")
            syncers_groups_in_cmk = []

            cache = self.get_cache_object(group=group_type)

            group_list = cache.content.get('list', [])

            for cmk_group in [x['href'] for x in cmks_groups[0]['value']]:
                cmk_name = cmk_group.split('/')[-1]
                if cmk_name in group_list:
                    syncers_groups_in_cmk.append(cmk_name)

            cache.content['list'] = configured_groups
            cache.save()



            print(f"{CC.OKBLUE} *{CC.ENDC} Create {group_type} if needed")
            entries = []
            new_group_names = []
            for new_group in configured_groups:
                new_group_names.append(new_group)
                if new_group not in syncers_groups_in_cmk:
                    print(f"{CC.OKBLUE}  *{CC.ENDC} Added {new_group}")
                    entries.append({
                        'alias' : new_group,
                        'name' : new_group,
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
                        messages.append(("INFO", f"Created Groups: {group_type} {data}"))
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
                        messages.append(("INFO", f"Deleted Group: {group_alias}"))
                        print(f"{CC.OKBLUE} *{CC.ENDC} Group {group_alias} deleted")

        log.log(f"Checkmk Group synced with {self.account_name}",
                    source="CMK_GROUP_SYNC", details=messages)
#.
#   .-- Export Bi Rules
    def export_bi_rules(self):
        """
        Export BI Rules
        """
        print(f"\n{CC.HEADER}Build needed Rules{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")


        for db_host in Host.objects(available=True):
            attributes = self.get_host_attributes(db_host, 'cmk_conf')
            if not attributes:
                continue
            host_actions = self.actions.get_outcomes(db_host, attributes['all'])
            unique_rules = {}
            related_packs = []
            if host_actions:
                for rule_type, rules in host_actions.items():
                    for rule_params in rules:
                        # Render Template Value
                        tpl = jinja2.Template(rule_params['rule_template'])
                        rule_body = \
                            tpl.render(HOSTNAME=db_host.hostname, **attributes['all'])
                        rule_dict = ast.literal_eval(rule_body)
                        unique_rules[rule_dict['id']] = rule_dict
                        related_packs.append(rule_dict['pack_id'])


        print(f"{CC.OKGREEN} -- {CC.ENDC} Load Rule Packs from Checkmk")
        found_list = []
        create_list = []
        sync_list = []
        delete_list = []
        unique_rules_keys = list(unique_rules.keys())
        for pack in related_packs:
            print(f"{CC.HEADER}Check Pack {pack} {CC.ENDC}")
            url = f"/objects/bi_pack/{pack}"
            response = self.request(url, method="GET")
            for cmk_rule in response[0]['members']['rules']['value']:
                cmk_rule_id = cmk_rule['href'].split('/')[-1]
                found_list.append(cmk_rule_id)
                if cmk_rule_id not in unique_rules_keys:
                    delete_list.append(cmk_rule_id)
            for local_rule in unique_rules_keys:
                if local_rule not in found_list:
                    create_list.append(local_rule)
                else:
                    sync_list.append(local_rule)

            for delete_id in delete_list:
                url = f"/objects/bi_rule/{delete_id}"
                del_response = self.request(url, method="DELETE")[1]
                print(f"{CC.WARNING} *{CC.ENDC} Rule {delete_id} deleted. Status: {del_response}")

            for create_id in create_list:
                url = f"/objects/bi_rule/{create_id}"
                data = unique_rules[create_id]
                self.request(url, data=data, method="POST")[0]
                print(f"{CC.OKGREEN} *{CC.ENDC} Rule {create_id} created.")

            for sync_id in sync_list:
                print(f"{CC.OKGREEN} *{CC.ENDC} Check {sync_id} for Changes.")
                url = f"/objects/bi_rule/{sync_id}"
                cmk_rule = self.request(url, method="GET")[0]
                if cmk_rule != unique_rules[sync_id]:
                    print(f"{CC.WARNING}   *{CC.ENDC} Sync needed")
                    data = unique_rules[sync_id]
                    self.request(url, data=data,  method="PUT")[0]
#.
