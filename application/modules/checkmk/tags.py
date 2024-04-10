"""
Checkmk Tag Syncronize
"""
#pylint: disable=logging-fstring-interpolation
import ast
import time
from application import logger
from application.modules.checkmk.config_sync import SyncConfiguration
from application.modules.debug import ColorCodes as CC
from application.modules.checkmk.models import CheckmkTagMngmt
from application.models.host import Host
from application.helpers.syncer_jinja import render_jinja
from application.modules.checkmk.helpers import cmk_cleanup_tag_id

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
                rendering = render_jinja(multi_list, **object_attributes['all'])
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
                        cmk_cleanup_tag_id(render_jinja(group_id_org, **data))

                    if new_group_id in self.groups:
                        # No need to Render Again and Again
                        logger.debug(f" --- Group Already Rendered: {new_group_id}")
                        continue

                    curr = self.groups[group_id_org]

                    outcome[new_group_id] = {}
                    outcome[new_group_id]['tags'] = []
                    outcome[new_group_id]['topic'] = render_jinja(curr['topic'], **data)
                    outcome[new_group_id]['title'] = render_jinja(curr['title'], **data)
                    outcome[new_group_id]['help'] = curr['help']
                    outcome[new_group_id]['ident'] = cmk_cleanup_tag_id(new_group_id)
                    outcome[new_group_id]['rw_id'] = render_jinja(curr['rw_id'], **data)
                    outcome[new_group_id]['rw_title'] = \
                                    render_jinja(curr['rw_title'], **data)
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
            if group_id in self._groups_used_as_template:
                continue

            # Check if we use data from the object
            if object_filter := group_data['object_filter']:
                if db_object.get_inventory()['syncer_account'] != object_filter:
                    logger.debug(f" --- Not matching object filter: {object_filter}")
                    continue


            rewrite_id = group_data['rw_id']
            rewrite_title = group_data['rw_title']

            new_tag_id = render_jinja(rewrite_id, HOSTNAME=hostname,
                                                **object_attributes['all'])
            new_tag_id = new_tag_id.strip()
            if new_tag_id:
                new_tag_id = cmk_cleanup_tag_id(new_tag_id)

            new_tag_title = render_jinja(rewrite_title, HOSTNAME=hostname,
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
