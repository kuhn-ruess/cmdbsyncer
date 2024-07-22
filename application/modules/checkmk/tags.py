"""
Checkmk Tag Syncronize
"""
#pylint: disable=logging-fstring-interpolation
import ast
import multiprocessing
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
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


    def build_caches(self, db_host, groups, multiply_expressions):
        """
        Calculation of rules and Host Tags
        """
        object_attributes = self.get_host_attributes(db_host, 'cmk_conf')

        tags_of_host = {}
        addional_groups = {}
        if multiply_expressions:
            cache_name_tags = 'cmk_tags_multiply_tags'
            cache_name_groups = 'cmk_tags_multiply_groups'
            if cache_name_tags not in db_host.cache or \
                    cache_name_groups not in db_host.cache:
                tags_of_host, addional_groups = \
                            self.check_for_multi_groups(object_attributes,
                                                        groups,
                                                        multiply_expressions)
                db_host.cache[cache_name_tags] = tags_of_host
                db_host.cache[cache_name_groups] = addional_groups

            tags_of_host = db_host.cache[cache_name_tags]
            addional_groups = db_host.cache[cache_name_groups]
            groups.update(addional_groups)


        cache_name = 'cmk_tags_tag_choices'
        if cache_name not in db_host.cache:
            logger.debug(f" -- Build Tag Cache {cache_name}")
            hosts_tags = self.get_tags_for_host(db_host, object_attributes,
                                                      groups, tags_of_host)
            db_host.cache[cache_name] = hosts_tags
        db_host.save()


    def calculate_rules(self):
        """
        Calculate needed rules
        """
        db_objects = CheckmkTagMngmt.objects(enabled=True)
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Calculating Needed Rules", total=total)
            manager = multiprocessing.Manager()
            base_groups = manager.dict()
            multiply_expressions = manager.list()
            with multiprocessing.Pool() as pool:
                for rule in db_objects:
                    pool.apply_async(self.create_inital_groups,
                                     args=(rule, base_groups, multiply_expressions),
                                     callback=lambda x: progress.advance(task1))
                pool.close()
                pool.join()
        return base_groups, multiply_expressions


    def export_tags(self):
        """
        Export Tags to Checkmk
        """
        base_groups, multiply_expressions = self.calculate_rules()

        total = Host.objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            manager = multiprocessing.Manager()
            groups = manager.dict()
            groups.update(base_groups)

            mlt_expressions = manager.list()
            mlt_expressions += multiply_expressions

            task1 = progress.add_task("Calculating Caches", total=total)
            with multiprocessing.Pool() as pool:
                for entry in Host.objects():
                    pool.apply_async(self.build_caches,
                                     args=(entry, groups, mlt_expressions),
                                     callback=lambda x: progress.advance(task1))
                pool.close()
                pool.join()

            task2 = progress.add_task("Apply Hosttags to objects", total=total)
            with multiprocessing.Pool() as pool:
                tags = manager.list()
                for entry in Host.objects():
                    pool.apply_async(self.update_hosts_tags,
                                     args=(entry, tags),
                                     callback=lambda x: progress.advance(task2))
                pool.close()
                pool.join()

        # Delete Templates
        for group_id, group in list(groups.items()):
            if group.get('is_template'):
                logger.debug(f"Delete Template {group_id}")
                del groups[group_id]


        self.sync_to_checkmk(groups, tags)

    def update_hosts_multigroups(self, db_host, groups):
        """
        Update the groups ob
        """
        cache_name = 'cmk_tags_multigroups'
        if cache_name not in db_host.cache:
            return
        multi_groups = db_host.cache[cache_name]

        for group_id, group_data in multi_groups.items():
            group_data['is_template'] = False
            groups[group_id] = group_data

    def update_hosts_tags(self, db_host, global_tags):
        """
        Update the Tags provided by the Host
        """
        cache_name = 'cmk_tags_tag_choices'
        if cache_name not in db_host.cache:
            return
        hosts_tags = db_host.cache[cache_name]

        for group_id, tags in hosts_tags.items():
            tag_id, tag_title = tags
            tag_tuple = (group_id, tag_id, tag_title)
            if tag_tuple not in global_tags:
                global_tags.append(tag_tuple)

    def create_inital_groups(self, rule, groups, multiply_expressions):
        """
        Create inital group Object
        """
        logger.debug(f"Get Rule {rule.group_id}")
        group_id = rule.group_id
        groups[group_id] =  {
            'tags': [],
            'topic': rule.group_topic_name,
            'title': rule.group_title,
            'help': rule.group_help,
            'ident': group_id, # set here to use it directly later
            'rw_id': rule.rewrite_id,
            'rw_title': rule.rewrite_title,
            'object_filter': rule.filter_by_account,
            'multiply_list': rule.group_multiply_list,
            'is_template': bool(rule.group_multiply_by_list),
        }
        if rule.group_multiply_by_list:
            expr_tuple = (group_id, rule.group_multiply_list)
            if expr_tuple not in multiply_expressions:
                multiply_expressions.append(expr_tuple)

    def check_for_multi_groups(self, object_attributes, groups, multiply_expressions):
        """
        Update the Group Config to,
        render special options
        """
        #pylint: disable=too-many-locals

        tags_of_host = {}
        addional_groups = {}

        data = object_attributes['all']
        for group_id_org, expression in multiply_expressions:
            try:
                rendering = render_jinja(expression, mode="raise", **data)
                if not rendering:
                    continue

                new_choices = ast.literal_eval(rendering)
                if not new_choices:
                    logger.debug(" --- No Choices")
                    continue
                for new_group_name in new_choices:
                    data['name'] = new_group_name
                    new_group_id = \
                        cmk_cleanup_tag_id(render_jinja(group_id_org, **data, mode="raise"))

                    curr = groups[group_id_org]
                    topic = render_jinja(curr['topic'], mode="raise",  **data)
                    title = render_jinja(curr['title'], mode="raise",  **data)
                    rw_id = render_jinja(curr['rw_id'], mode="raise",  **data)
                    rw_title = render_jinja(curr['rw_title'], mode="raise", **data)

                    addional_groups[new_group_id] = {
                        'tags': [],
                        'topic': topic,
                        'title': title,
                        'help': curr['help'],
                        'ident': new_group_id,
                        'rw_id': rw_id,
                        'rw_title': rw_title,
                        'object_filter': curr['object_filter'],
                    }

                    tags_of_host[new_group_id] = (rw_id, rw_title)
            except Exception as _error:
                continue
        return tags_of_host, addional_groups

    def get_tags_for_host(self, db_object, object_attributes,
                                groups, tags_of_host):
        """
        Search all tags which this Host can provide
        """
        hostname = db_object.hostname
        tags = {}
        logger.debug(f"Update Tags from {hostname}")


        for group_id, group_data in groups.items():
            if group_data.get('is_template'):
                continue

            new_tag_id, new_tag_title = False, False

            if tags_of_host.get(group_id):
                new_tag_id, new_tag_title = tags_of_host[group_id]
            else:
                # Check if we use data from the object
                if object_filter := group_data.get('object_filter'):
                    if db_object.get_inventory().get('syncer_account') != object_filter:
                        logger.debug(f" --- Not matching object filter: {object_filter}")
                        continue


                try:
                    rewrite_id = group_data['rw_id']
                    rewrite_title = group_data['rw_title']

                    new_tag_id = render_jinja(rewrite_id, HOSTNAME=hostname,
                                              **object_attributes['all'])
                    new_tag_id = new_tag_id.strip()



                    if new_tag_id:
                        new_tag_id = cmk_cleanup_tag_id(new_tag_id)

                    new_tag_title = render_jinja(rewrite_title, HOSTNAME=hostname,
                                                 **object_attributes['all'])
                    new_tag_title.strip()
                except Exception:
                    new_tag_id, new_tag_title = False, False

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
        found_ids = []
        tags = []
        for x, y in config_tags:
            if x not in found_ids:
                tags.append({'ident':x, 'title': y})
                found_ids.append(x)

        if not tags or len(tags) == 0:
            print(f"{CC.WARNING} *{CC.ENDC} Group has no tags")
            return False
        return tags

    def sync_to_checkmk(self, groups, tag_group_list):
        """
        Use generated configuration to Sync
        Everhting to Checkmk
        """
        etag, checkmk_ids = self.get_checkmk_tags()

        create_url = "/domain-types/host_tag_group/collections/all"
        logger.debug(f"All Groups: {groups}")
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Sending to Checkmk", total=len(groups))
            for syncer_group_id, syncer_group_data in groups.items():
                payload = syncer_group_data.copy()
                for what in ['object_filter', 'rw_id', 'is_template',
                             'rw_title', 'multiply_list']:
                    if what in payload:
                        del payload[what]

                tag_list = [(x[1], x[2]) for x in tag_group_list if x[0] == syncer_group_id]
                if tags := self.prepare_tags_for_checkmk(tag_list):
                    payload['tags'] = tags
                else:
                    continue
                if syncer_group_id not in checkmk_ids:
                    # Create the group
                    self.request(create_url, method="POST", data=payload)
                    progress.console.print(f" * Group {syncer_group_id} created.")
                else:
                    # Check if we need to update it
                    checkmk_tags = checkmk_ids[syncer_group_id]
                    flat = [ {'ident': x['id'], 'title': x['title']} for x in checkmk_tags]

                    if flat == payload['tags']:
                        progress.console.print(f" * Group {syncer_group_id} already up to date.")
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
                            print(error)
                            progress.console.print(f" ! Group {syncer_group_id} can't be updated.")
                            logger.debug(error)
                        else:
                            progress.console.print(f" - Group {syncer_group_id} updated.")
                progress.update(task1, advance=1)
