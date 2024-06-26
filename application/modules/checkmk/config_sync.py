"""
Checkmk Configuration
"""
#pylint: disable=import-error, too-many-locals, no-member
#pylint: disable=logging-fstring-interpolation
import ast
from mongoengine.errors import DoesNotExist
from application import log, logger
from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.checkmk.models import (
        CheckmkGroupRule,
        CheckmkObjectCache,
        CheckmkUserMngmt
        )
from application.modules.debug import ColorCodes as CC
from application.models.host import Host
from application.modules.rule.rule import Rule
from application.helpers.syncer_jinja import render_jinja


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
                        new_group_name = render_jinja(outcome.rewrite,
                                                                name=key, result=key)
                    new_group_name = str_replace(new_group_name, replace_exceptions).strip()
                    if rewrite_title:
                        new_group_title = render_jinja(outcome.rewrite_title,
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
                        new_group_name = render_jinja(outcome.rewrite,
                                                      name=value, result=value)
                    new_group_name = str_replace(new_group_name, replace_exceptions).strip()
                    if rewrite_title:
                        new_group_title = render_jinja(outcome.rewrite_title,
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
                        new_group_name = render_jinja(outcome.rewrite_name,
                                                      name=value, result=value)
                    new_group_name = str_replace(new_group_name, replace_exceptions).strip()
                    if rewrite_title:
                        new_group_title = render_jinja(outcome.rewrite_title,
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
                            render_jinja(rule_params['rule_template'],
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
                            render_jinja(rule_params['rule_template'],
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
