"""
Checkmk Configuration
"""
#pylint: disable=import-error, too-many-locals, too-many-branches, too-many-statements, no-member
import ast
import jinja2
from mongoengine.errors import DoesNotExist
from application import log
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.checkmk.models import CheckmkGroupRule, CheckmkObjectCache
from application.modules.debug import ColorCodes as CC
from application.models.host import Host

class SyncConfiguration(CMK2):
    """
    Sync jobs for Checkmk Config
    """

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

        # pylint: disable=too-many-nested-blocks
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

                        # Overwrite the Params again
                        rule_params['value'] = value
                        del rule_params['value_template']

                        if rule_params['condition_label_template']:
                            label_condition_tpl = \
                                jinja2.Template(rule_params['condition_label_template'])
                            label_condition = \
                                label_condition_tpl.render(HOSTNAME=db_host.hostname, \
                                                                **attributes['all'])

                            label_key, label_value = label_condition.split(':')
                            # Fix bug in case of empty Labels in store
                            if not label_key or not label_value:
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
                    'value_raw' : rule['value'],
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
        replace_exceptions = ['-', '_']
        for rule in CheckmkGroupRule.objects(enabled=True):
            outcome = rule.outcome
            group_type = outcome.group_name
            groups.setdefault(group_type, [])
            rewrite_name = False
            rewrite_title = False
            if outcome.rewrite:
                rewrite_name = True
                rewrite_name_tpl = jinja2.Template(outcome.rewrite)
            if outcome.rewrite_title:
                rewrite_title = True
                rewrite_title_tpl = jinja2.Template(outcome.rewrite_title)
            if outcome.foreach_type == 'value':

                if outcome.foreach.endswith('*'):
                    keys = []
                    search = outcome.foreach[:-1]
                    for key, keys_values in attributes[0].items():
                        if key.startswith(search):
                            keys += keys_values
                else:
                    keys = attributes[1].get(outcome.foreach, [])


                for key in keys:
                    new_group_title = key
                    new_group_name = key
                    if rewrite_name:
                        new_group_name = rewrite_name_tpl.render(name=key, result=key)
                    new_group_name = self.replace(new_group_name, replace_exceptions).strip()
                    if rewrite_title:
                        new_group_title = rewrite_title_tpl.render(name=key, result=key)
                    new_group_title = self.replace(new_group_title, replace_exceptions).strip()

                    if new_group_name and (new_group_title, new_group_name) not in groups[group_type]:
                        groups[group_type].append((new_group_title, new_group_name))
            elif outcome.foreach_type == 'label':
                if outcome.foreach.endswith('*'):
                    values = []
                    search = outcome.foreach[:-1]
                    for label, label_values in attributes[0].items():
                        if label.startswith(search):
                            values += label_values
                else:
                    values = attributes[0].get(outcome.foreach, [])

                for value in values:
                    new_group_title = value
                    new_group_name = value
                    if rewrite_name:
                        new_group_name = rewrite_name_tpl.render(name=value, result=value)
                    new_group_name = self.replace(new_group_name, replace_exceptions).strip()
                    if rewrite_title:
                        new_group_title = rewrite_title_tpl.render(name=value, result=value)
                    new_group_title = self.replace(new_group_title, replace_exceptions).strip()
                    if new_group_name and (new_group_title, new_group_name) not in groups[group_type]:
                        groups[group_type].append((new_group_title, new_group_name))

        print(f"\n{CC.HEADER}Start Sync{CC.ENDC}")
        urls = {
            'contact_groups': {
                'get': "/domain-types/contact_group_config/collections/all",
                'put': "/domain-types/contact_group_config/actions/bulk-create/invoke",
                'delete': "/objects/contact_group_config/",
                'update': "/domain-types/contact_group_config/actions/bulk-update/invoke"
            },
            'host_groups' : {
                'get': "/domain-types/host_group_config/collections/all",
                'put': "/domain-types/host_group_config/actions/bulk-create/invoke",
                'delete': "/objects/host_group_config/",
                'update': "/domain-types/host_group_config/actions/bulk-update/invoke"
            },
            'service_groups' : {
                'get': "/domain-types/service_group_config/collections/all",
                'put': "/domain-types/service_group_config/actions/bulk-create/invoke",
                'delete': "/objects/service_group_config/",
                'update': "/domain-types/service_group_config/actions/bulk-update/invoke"
            },
        }
        for group_type, configured_groups in groups.items():
            print(f"{CC.OKBLUE} *{CC.ENDC} Read Current {group_type}")
            url = urls[group_type]['get']

            cmks_groups = self.request(url, method="GET")
            syncers_groups_in_cmk = []
            syncers_groups_needing_update = []

            cache = self.get_cache_object(group=group_type)

            group_list = cache.content.get('list', [])


            for cmk_group in cmks_groups[0]['value']:
                cmk_name = cmk_group['id']
                cmk_title = cmk_group['title']
                # From Cache we get Lists not tuple
                if [cmk_title, cmk_name] in group_list:
                    syncers_groups_in_cmk.append(cmk_name)
                elif cmk_name in [x[1] for x in group_list]:
                    syncers_groups_needing_update.append(cmk_name)

            cache.content['list'] = configured_groups
            cache.save()


            print(f"{CC.OKBLUE} *{CC.ENDC} Create {group_type} if needed")
            new_entries = []
            update_entries = []
            handeled_groups = []
            for new_group in configured_groups:
                handeled_groups.append(new_group)
                alias = new_group[0]
                name = new_group[1]
                if name not in syncers_groups_in_cmk and name not in syncers_groups_needing_update:
                    print(f"{CC.OKBLUE}  *{CC.ENDC} Added {new_group}")
                    new_entries.append({
                        'alias' : alias,
                        'name' : name,
                    })
                elif name in syncers_groups_needing_update:
                    print(f"{CC.OKBLUE}  *{CC.ENDC} Updated {new_group}")
                    update_entries.append({
                        'name' : name,
                        "attributes" : {
                            "alias": alias,
                        }
                    })

            if new_entries:
                data = {
                    'entries': new_entries,
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
            if update_entries:
                data = {
                    'entries': update_entries,
                }
                url = urls[group_type]['update']
                if test_run:
                    print(f"\n{CC.HEADER}Output only (Testrun){CC.ENDC}")
                else:
                    print(f"\n{CC.HEADER}Send {group_type} to Checkmk{CC.ENDC}")
                    try:
                        self.request(url, data=data, method="PUT")
                        messages.append(("INFO", f"Update Groups: {group_type} {data}"))
                    except CmkException as error:
                        print(f"{CC.FAIL} {error} {CC.ENDC}")
                        return


            if not test_run:
                print(f"{CC.OKBLUE} *{CC.ENDC} Delete Groups if needed")
                for name in syncers_groups_in_cmk:
                    if name not in [x[1] for x in handeled_groups]:
                        # Checkmk is not deleting objects if the still referenced
                        url = f"{urls[group_type]['delete']}{name}"
                        self.request(url, method="DELETE")
                        messages.append(("INFO", f"Deleted Group: {name}"))
                        print(f"{CC.OKBLUE} *{CC.ENDC} Group {name} deleted")

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


        unique_rules = {}
        related_packs = []
        for db_host in Host.objects(available=True):
            attributes = self.get_host_attributes(db_host, 'cmk_conf')
            if not attributes:
                continue
            host_actions = self.actions.get_outcomes(db_host, attributes['all'])
            if host_actions:
                for _rule_type, rules in host_actions.items():
                    for rule_params in rules:
                        # Render Template Value
                        tpl = jinja2.Template(rule_params['rule_template'])
                        rule_body = \
                            tpl.render(HOSTNAME=db_host.hostname, **attributes['all'])
                        rule_dict = ast.literal_eval(rule_body.replace('null', 'None'))
                        unique_rules[rule_dict['id']] = rule_dict
                        pack_id = rule_dict['pack_id']
                        if pack_id not in related_packs:
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
                self.request(url, data=data, method="POST")
                print(f"{CC.OKGREEN} *{CC.ENDC} Rule {create_id} created.")

            for sync_id in sync_list:
                print(f"{CC.OKGREEN} *{CC.ENDC} Check {sync_id} for Changes.")
                url = f"/objects/bi_rule/{sync_id}"
                cmk_rule = self.request(url, method="GET")[0]
                if cmk_rule != unique_rules[sync_id]:
                    print(f"{CC.WARNING}   *{CC.ENDC} Sync needed")
                    data = unique_rules[sync_id]
                    self.request(url, data=data,  method="PUT")
#.
#   .-- Export BI Aggregations
    def export_bi_aggregations(self):
        """
        Export BI Aggregations
        """
        print(f"\n{CC.HEADER}Build needed Aggregations{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")


        unique_aggregations = {}
        related_packs = []
        for db_host in Host.objects(available=True):
            attributes = self.get_host_attributes(db_host, 'cmk_conf')
            if not attributes:
                continue
            host_actions = self.actions.get_outcomes(db_host, attributes['all'])
            if host_actions:
                for _rule_type, rules in host_actions.items():
                    for rule_params in rules:
                        # Render Template Value
                        tpl = jinja2.Template(rule_params['rule_template'])
                        rule_body = \
                            tpl.render(HOSTNAME=db_host.hostname, **attributes['all'])
                        aggregation_dict = ast.literal_eval(rule_body.replace('null', 'None'))
                        unique_aggregations[aggregation_dict['id']] = aggregation_dict
                        pack_id = aggregation_dict['pack_id']
                        if pack_id not in related_packs:
                            related_packs.append(pack_id)


        print(f"{CC.OKGREEN} -- {CC.ENDC} Load Rule Packs from Checkmk")
        found_list = []
        create_list = []
        sync_list = []
        delete_list = []
        unique_aggregation_keys = list(unique_aggregations.keys())
        for pack in related_packs:
            print(f"{CC.HEADER}Check Pack {pack} {CC.ENDC}")
            url = f"/objects/bi_pack/{pack}"
            response = self.request(url, method="GET")
            for cmk_rule in response[0]['members']['aggregations']['value']:
                cmk_rule_id = cmk_rule['href'].split('/')[-1]
                found_list.append(cmk_rule_id)
                if cmk_rule_id not in unique_aggregation_keys:
                    delete_list.append(cmk_rule_id)
            for local_rule in unique_aggregation_keys:
                if local_rule not in found_list:
                    create_list.append(local_rule)
                else:
                    sync_list.append(local_rule)

            for delete_id in delete_list:
                url = f"/objects/bi_aggregation/{delete_id}"
                del_response = self.request(url, method="DELETE")[1]
                print(f"{CC.WARNING} *{CC.ENDC} Aggr. {delete_id} deleted. Resp: {del_response}")

            for create_id in create_list:
                url = f"/objects/bi_aggregation/{create_id}"
                data = unique_aggregations[create_id]
                self.request(url, data=data, method="POST")
                print(f"{CC.OKGREEN} *{CC.ENDC} Aggregation {create_id} created.")

            for sync_id in sync_list:
                print(f"{CC.OKGREEN} *{CC.ENDC} Check Aggregation {sync_id} for Changes.")
                url = f"/objects/bi_aggregation/{sync_id}"
                cmk_rule = self.request(url, method="GET")[0]
                if cmk_rule != unique_aggregations[sync_id]:
                    print(f"{CC.WARNING}   *{CC.ENDC} Sync needed")
                    data = unique_aggregations[sync_id]
                    self.request(url, data=data,  method="PUT")
#.
