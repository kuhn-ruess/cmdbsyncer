"""
Checkmk Groups Export
"""
from mongoengine.errors import DoesNotExist

from application.modules.checkmk.cmk2 import CMK2, CmkException
from application.modules.rule.rule import Rule
from application.modules.checkmk.models import CheckmkGroupRule

from application.modules.checkmk.models import CheckmkObjectCache

from syncerapi.v1 import render_jinja, cc as CC, Host


str_replace = Rule.replace

class CheckmkGroupSync(CMK2):
    """
    Syncronize Checkmk Groups
    """
    name = "Sync Checkmk Groups"
    source = "cmk_group_sync"

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

    def export_cmk_groups(self, test_run):# pylint: disable=too-many-branches, too-many-statements
        """
        Export all Checkmk Groups
        """
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
                        self.log_details.append(("INFO", f"Created Groups: {group_type} {data}"))
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
                        self.log_details.append(("INFO", f"Update Groups: {group_type} {data}"))
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
                        self.log_details.append(("INFO", f"Deleted Group: {name}"))
                        print(f"{CC.OKBLUE} *{CC.ENDC} Group {name} deleted")
