"""
Checkmk Configuration
"""
#pylint: disable=import-error, too-many-locals, no-member
#pylint: disable=logging-fstring-interpolation
import ast
import time
from flask import render_template_string
from mongoengine.errors import DoesNotExist
from application import log, logger, cmk_cleanup_tag_id
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.checkmk.models import (
        CheckmkGroupRule,
        CheckmkObjectCache,
        CheckmkTagMngmt,
        CheckmkUserMngmt
        )
from application.modules.debug import ColorCodes as CC
from application.models.host import Host
from application.modules.rule.rule import Rule


str_replace = Rule.replace

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
        for db_host in Host.objects():
            if attributes := self.get_host_attributes(db_host, 'cmk_conf'):
                for key, value in attributes['all'].items():
                    key, value = str(key), str(value)
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
    def export_cmk_rules(self): # pylint: disable=too-many-branches, too-many-statements
        """
        Export config rules to checkmk
        """
        messages = []
        print(f"\n{CC.HEADER}Build needed Rules{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")

        rulsets_by_type = {}

        # pylint: disable=too-many-nested-blocks
        for db_host in Host.objects():
            attributes = self.get_host_attributes(db_host, 'cmk_conf')
            if not attributes:
                continue
            host_actions = self.actions.get_outcomes(db_host, attributes['all'])
            if host_actions:
                for rule_type, rules in host_actions.items():
                    for rule_params in rules:
                        # Render Template Value
                        condition_tpl = {"host_tags": [], "service_labels": []}
                        value = \
                            render_template_string(rule_params['value_template'],
                                                   HOSTNAME=db_host.hostname, **attributes['all'])

                        # Overwrite the Params again
                        rule_params['value'] = value
                        del rule_params['value_template']

                        if rule_params['condition_label_template']:
                            label_condition = \
                                render_template_string(rule_params['condition_label_template'],
                                                       HOSTNAME=db_host.hostname,
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
                            host_condition = \
                                render_template_string(rule_params['condition_host'],
                                                       HOSTNAME=db_host.hostname,
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
                        # pylint: disable=unnecessary-dict-index-lookup
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
#location   .-- Export Group

    def export_cmk_groups(self, test_run):# pylint: disable=too-many-branches, too-many-statements
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
            if outcome.rewrite_title:
                rewrite_title = True
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
                        new_group_name = render_template_string(outcome.rewrite,
                                                                name=key, result=key)
                    new_group_name = str_replace(new_group_name, replace_exceptions).strip()
                    if rewrite_title:
                        new_group_title = render_template_string(outcome.rewrite_title,
                                                                 name=key, result=key)
                    new_group_title = str_replace(new_group_title, replace_exceptions).strip()

                    if new_group_name and (new_group_title, new_group_name) \
                                                            not in groups[group_type]:
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
                        new_group_name = render_template_string(outcome.rewrite,
                                                                name=value, result=value)
                    new_group_name = str_replace(new_group_name, replace_exceptions).strip()
                    if rewrite_title:
                        new_group_title = render_template_string(outcome.rewrite_title,
                                                                 name=value, result=value)
                    new_group_title = str_replace(new_group_title, replace_exceptions).strip()
                    if new_group_name and (new_group_title, new_group_name) \
                                                        not in groups[group_type]:
                        groups[group_type].append((new_group_title, new_group_name))
            elif outcome.foreach_type == "object":
                db_filter = {
                    'is_object': True
                }
                object_filter = outcome.foreach
                if object_filter:
                    db_filter['inventory__syncer_account'] = object_filter
                for entry in Host.objects(**db_filter):
                    value = entry.hostname
                    new_group_title = value
                    new_group_name = value
                    if rewrite_name:
                        new_group_name = render_template_string(outcome.rewrite_name,
                                                                name=value, result=value)
                    new_group_name = str_replace(new_group_name, replace_exceptions).strip()
                    if rewrite_title:
                        new_group_title = render_template_string(outcome.rewrite_title,
                                                                 name=value, result=value)
                    new_group_title = str_replace(new_group_title, replace_exceptions).strip()
                    if new_group_name and (new_group_title, new_group_name) \
                                                        not in groups[group_type]:
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
            yet_external_groups_in_cmk = []

            group_cache = self.get_cache_object(group=group_type)

            cached_group_list = group_cache.content.get('list', [])



            # Check which CMK Groups are in our CACHE
            for cmk_group in cmks_groups[0]['value']:
                if 'id' in cmk_group:
                    cmk_name = cmk_group['id']
                else:
                    # Support Checkmk 2.1x
                    cmk_name = cmk_group['href'].split('/')[-1]
                cmk_title = cmk_group['title']

                # From Cache we get Lists not tuple
                if [cmk_title, cmk_name] in cached_group_list:
                    syncers_groups_in_cmk.append(cmk_name)
                elif cmk_name in [x[1] for x in cached_group_list]:
                    syncers_groups_needing_update.append(cmk_name)
                else:
                    # The Group is not known yet, but maybe we need to controll it
                    yet_external_groups_in_cmk.append(cmk_name)

            group_cache.content['list'] = configured_groups
            group_cache.save()


            print(f"{CC.OKBLUE} *{CC.ENDC} Create {group_type} if needed")
            new_entries = []
            update_entries = []
            handeled_groups = []
            for new_group in configured_groups:
                handeled_groups.append(new_group)
                alias = new_group[0]
                name = new_group[1]
                if "None" in (alias, name):
                    continue
                if name not in syncers_groups_in_cmk and name not in syncers_groups_needing_update:
                    print(f"{CC.OKBLUE}  *{CC.ENDC} Added {new_group}")
                    new_entries.append({
                        'alias' : alias,
                        'name' : name,
                    })
                elif name in syncers_groups_needing_update or name in yet_external_groups_in_cmk:
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
    def export_bi_rules(self):# pylint: disable=too-many-branches, too-many-statements
        """
        Export BI Rules
        """
        print(f"\n{CC.HEADER}Build needed Rules{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")


        unique_rules = {}
        related_packs = []
        for db_host in Host.objects():
            attributes = self.get_host_attributes(db_host, 'cmk_conf')
            if not attributes:
                continue
            host_actions = self.actions.get_outcomes(db_host, attributes['all'])
            if host_actions:
                for _rule_type, rules in host_actions.items():
                    for rule_params in rules:
                        # Render Template Value
                        rule_body = \
                            render_template_string(rule_params['rule_template'],
                                                   HOSTNAME=db_host.hostname, **attributes['all'])
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
    def export_bi_aggregations(self): #pylint: disable=too-many-branches
        """
        Export BI Aggregations
        """
        print(f"\n{CC.HEADER}Build needed Aggregations{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")


        unique_aggregations = {}
        related_packs = []
        for db_host in Host.objects():
            attributes = self.get_host_attributes(db_host, 'cmk_conf')
            if not attributes:
                continue
            host_actions = self.actions.get_outcomes(db_host, attributes['all'])
            if host_actions:
                for _rule_type, rules in host_actions.items():
                    for rule_params in rules:
                        # Render Template Value
                        rule_body = \
                            render_template_string(rule_params['rule_template'],
                                                   HOSTNAME=db_host.hostname, **attributes['all'])
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
#   . Export Checkmk User
    def export_users(self):
        """
        Export Checkmk Users
        """
        checks = [
            'fullname', 'disable_login',
            'pager_address', 'contactgroups',
            'roles', 'contact_options.email',
        ]
        for user in CheckmkUserMngmt.objects(disabled__ne=True):
            url = f"/objects/user_config/{user.user_id}"
            cmk_user = self.request(url, method="GET")
            # ({}, {'status_code': 404})
            user_template = {
              "username": user.user_id,
              "fullname": user.full_name,
              "auth_option": {
                "auth_type": "password",
                "password": user.password
              },
              "disable_login": user.disable_login,
              "contact_options": {
                "email": user.email
              },
              "pager_address": user.pager_address,
              "idle_timeout": {
                "option": "global"
              },
              "roles": user.roles,
              #"authorized_sites": [
              #  "heute"
              #],
              "contactgroups": user.contact_groups,
              "disable_notifications": {
                "disable": False
              },
              "language": "en",
              "temperature_unit": "celsius",
              "interface_options": {
                "interface_theme": "dark"
              },
            }
            if not cmk_user[0]:
                if user.remove_if_found:
                    continue
                # We need to create the user
                print(f"{CC.OKGREEN} *{CC.ENDC} {user.user_id}: Created")
                url = "/domain-types/user_config/collections/all"
                response = self.request(url, data=user_template, method="POST")
                logger.debug(f"Response {response}")
            else:
                # We May Update the User (or delete him)
                if user.remove_if_found:
                    print(f"{CC.OKGREEN} *{CC.ENDC} {user.user_id}: Deleted")
                    self.request(url, method="DELETE")
                    continue

                etag = cmk_user[1]['ETag']
                cmk_data = cmk_user[0]['extensions']
                changed = False
                for check in checks:
                    if '.' in check:
                        first_level, second_level = check.split('.')
                        cmk_current = cmk_data.get(first_level,{}).get(second_level)
                        tmpl_current = user_template[first_level][second_level]
                    else:
                        cmk_current = cmk_data.get(check)
                        tmpl_current = user_template[check]
                    if cmk_current != tmpl_current:
                        changed = True
                        logger.debug(f"{check}: {tmpl_current} vs {cmk_current}")
                if changed or user.overwrite_password:
                    if not user.overwrite_password:
                        del user_template['auth_option']
                    del user_template['username']
                    update_headers = {
                        'if-match': etag
                    }
                    update_url = f"/objects/user_config/{user.user_id}"
                    print(f"{CC.OKGREEN} *{CC.ENDC} {user.user_id}: Updated")
                    self.request(update_url, method="PUT",
                        data=user_template,
                        additional_header=update_headers)
                else:
                    print(f"{CC.OKGREEN} *{CC.ENDC} {user.user_id}: Nothing to do")
#.

#   . Export Tags

class CheckmkTagSync(SyncConfiguration):
    """
    Syncronize Checkmk Tags
    """
    groups = {}
    _groups_used_as_template = []


    def export_tags(self):
        """
        Export Tags to Checkmk
        """
        print(f"{CC.OKGREEN} -- {CC.ENDC} Read all Rules and group them")
        start_time = time.time()
        db_objects = CheckmkTagMngmt.objects(enabled=True)
        total = db_objects.count()
        counter = 0
        logger.debug(f"-- {time.time() - start_time} seconds")
        for rule in db_objects:
            start_time = time.time()
            counter += 1
            self.create_inital_groups(rule)
            process = 100.0 * counter / total
            logger.debug(f"-- {time.time() - start_time} seconds")
            print(f"\n{CC.OKBLUE}({process:.0f}%){CC.ENDC} {rule.group_id}", end="")
        print()


        print(f"{CC.OKGREEN} -- {CC.ENDC} Read all Host Attribute and Build Tag list")
        start_time = time.time()
        total = Host.objects.count()
        counter = 0
        logger.debug(f"-- {time.time() - start_time} seconds")
        for entry in Host.objects():
            start_time = time.time()
            counter += 1

            self.update_hosts_multigroups(entry)
            self.update_hosts_tags(entry)

            process = 100.0 * counter / total
            logger.debug(f"{time.time() - start_time} seconds")
            entry.save()
            print(f"\n{CC.OKBLUE}({process:.0f}%){CC.ENDC} {entry.hostname}", end="")
        print()

        # Delete Templates
        for group_id in self._groups_used_as_template:
            logger.debug(f"Delete Template {group_id}")
            del self.groups[group_id]
        self.sync_to_checkmk()


    def update_hosts_multigroups(self, db_host):
        """
        Update the groups ob
        """

        cache_name = 'cmk_tags_multigroups'
        if cache_name in db_host.cache:
            logger.debug(f" -- Use Cache {cache_name}")
            multi_groups = db_host.cache[cache_name]
        else:
            logger.debug(f" -- Build Cache {cache_name}")
            object_attributes = self.get_host_attributes(db_host, 'cmk_conf')
            multi_groups = self.check_for_multi_groups(object_attributes)
            db_host.cache[cache_name] = multi_groups

        self.groups.update(multi_groups)


    def update_hosts_tags(self, db_host):
        """
        Update the Tags provided by the Host
        """

        object_attributes = self.get_host_attributes(db_host, 'cmk_conf')
        cache_name = 'cmk_tags_tag_choices'
        if cache_name in db_host.cache:
            logger.debug(f" -- Use Cache {cache_name}")
            hosts_tags = db_host.cache[cache_name]
        else:
            logger.debug(f" -- Build Cache {cache_name}")
            hosts_tags = self.update_groups_with_tags(db_host, object_attributes)
            db_host.cache[cache_name] = hosts_tags

        for group_id, tags in hosts_tags.items():
            tag_id, tag_title = tags
            if tag_id and (tag_id, tag_title) \
                        not in self.groups[group_id]['tags']:
                # we check not only, if the combination is uniue,
                # but also if also the id is not duplicate even with diffrent name
                if tag_id not in [x[0] for x in self.groups[group_id]['tags']]:
                    self.groups[group_id]['tags'].append((tag_id, tag_title))

    def create_inital_groups(self, rule):
        """
        Create inital group Object
        """
        logger.debug(f"Get Rule {rule.group_id}")
        group_id = rule.group_id
        self.groups.setdefault(group_id, {'tags':[]})
        self.groups[group_id]['topic'] = rule.group_topic_name
        self.groups[group_id]['title'] = rule.group_title
        self.groups[group_id]['help'] = rule.group_help
        self.groups[group_id]['ident'] = group_id # set here to use it directly later
        self.groups[group_id]['rw_id'] = rule.rewrite_id
        self.groups[group_id]['rw_title'] = rule.rewrite_title
        self.groups[group_id]['object_filter'] = rule.filter_by_account
        if rule.group_multiply_by_list:
            self.groups[group_id]['multiply_list'] = rule.group_multiply_list


    def check_for_multi_groups(self, object_attributes):
        """
        Update the Group Config to,
        render special options
        """

        outcome = {}
        for group_id_org in list(self.groups.keys()):

            if multi_list := self.groups[group_id_org].get('multiply_list'):
                logger.debug(f"-- Work on Multi Group {group_id_org}")
                rendering = render_template_string(multi_list, **object_attributes['all'])
                logger.debug(f" --- New Render: {rendering}")
                if not rendering:
                    continue

                new_choices = ast.literal_eval(rendering)

                if not new_choices:
                    logger.debug(" --- No Choices")
                    continue

                for newone in new_choices:
                    data = {
                        'name': newone,
                    }
                    new_group_id = \
                        cmk_cleanup_tag_id(render_template_string(group_id_org, **data))

                    if new_group_id in self.groups:
                        # No need to Render Again and Again
                        logger.debug(f" --- Group Already Rendered: {new_group_id}")
                        continue

                    curr = self.groups[group_id_org]

                    outcome[new_group_id] = {}
                    outcome[new_group_id]['tags'] = []
                    outcome[new_group_id]['topic'] = render_template_string(curr['topic'], **data)
                    outcome[new_group_id]['title'] = render_template_string(curr['title'], **data)
                    outcome[new_group_id]['help'] = curr['help']
                    outcome[new_group_id]['ident'] = cmk_cleanup_tag_id(new_group_id)
                    outcome[new_group_id]['rw_id'] = cmk_cleanup_tag_id(newone)
                    outcome[new_group_id]['rw_title'] = newone
                    outcome[new_group_id]['object_filter'] = curr['object_filter']

                # Mark as  'Template' Group,
                # So that we later can delete it
                if group_id_org not in self._groups_used_as_template:
                    self._groups_used_as_template.append(group_id_org)
        return outcome

    def update_groups_with_tags(self, db_object, object_attributes):
        """
        Search all tags which this Host can provide
        """
        hostname = db_object.hostname
        tags = {}
        logger.debug(f"Update Tags from {hostname}")

        for group_id, group_data in self.groups.items():

            # Check if we use data from the object
            if object_filter := group_data['object_filter']:
                if db_object.get_inventory()['syncer_account'] != object_filter:
                    logger.debug(f" --- Not matching object filter: {object_filter}")
                    continue


            rewrite_id = group_data['rw_id']
            rewrite_title = group_data['rw_title']

            print(object_attributes['all'])
            new_tag_id = render_template_string(rewrite_id, HOSTNAME=hostname,
                                                **object_attributes['all'])
            new_tag_id = new_tag_id.strip()
            if new_tag_id:
                new_tag_id = cmk_cleanup_tag_id(new_tag_id)

            new_tag_title = render_template_string(rewrite_title, HOSTNAME=hostname,
                                                   **object_attributes['all'])
            if new_tag_id and new_tag_title:
                tags[group_id] = (new_tag_id, new_tag_title)
        return tags



    def get_checkmk_tags(self):
        """
        Get list of current Tags in Checkmk
        """
        url = "/domain-types/host_tag_group/collections/all"
        response = self.request(url, method="GET")
        etag = response[1]['ETag']

        checkmk_ids = {}
        for group in response[0]['value']:
            checkmk_ids[group['id']] = group['extensions']['tags']
        return etag, checkmk_ids

    def prepare_tags_for_checkmk(self, config_tags):
        """
        Prepare the Tag Payload for Checkmk
        """
        if not config_tags:
            return False
        config_tags.sort(key=lambda tup: tup[1])
        if len(config_tags) > 1:
            config_tags.insert(0, (None, "Not set"))

        tags = [{'ident':x, 'title': y} for x,y in config_tags]
        if not tags or len(tags) == 0:
            print(f"{CC.WARNING} *{CC.ENDC} Group has no tags")
            return False
        return tags

    def sync_to_checkmk(self):
        """
        Use generated configuration to Sync
        Everhting to Checkmk
        """
        etag, checkmk_ids = self.get_checkmk_tags()

        create_url = "/domain-types/host_tag_group/collections/all"
        logger.debug(f"All Groups: {self.groups}")
        for syncer_group_id, syncer_group_data in self.groups.items():
            payload = syncer_group_data.copy()
            for what in ['object_filter', 'rw_id',
                         'rw_title', 'multiply_list']:
                if what in payload:
                    del payload[what]

            if tags := self.prepare_tags_for_checkmk(payload['tags'].copy()):
                payload['tags'] = tags
            else:
                continue
            if syncer_group_id not in checkmk_ids:
                # Create the group
                self.request(create_url, method="POST", data=payload)
                print(f"{CC.OKGREEN} *{CC.ENDC} Group {syncer_group_id} created.")
            else:
                # Check if we need to update it
                checkmk_tags = checkmk_ids[syncer_group_id]
                flat = [ {'ident': x['id'], 'title': x['title']} for x in checkmk_tags]

                if flat == payload['tags']:
                    print(f"{CC.OKBLUE} *{CC.ENDC} Group {syncer_group_id} already up to date.")
                else:
                    url = f"/objects/host_tag_group/{syncer_group_id}"
                    update_headers = {
                        'if-match': etag
                    }
                    del payload['ident']
                    payload['repair'] = True
                    try:
                        self.request(url,
                            method="PUT",
                            data=payload,
                            additional_header=update_headers)
                    except Exception as error:
                        print(f"{CC.WARNING} *{CC.ENDC} Group {syncer_group_id} can't be updated.")
                        logger.debug(error)
                    else:
                        print(f"{CC.OKCYAN} *{CC.ENDC} Group {syncer_group_id} updated.")

#.
