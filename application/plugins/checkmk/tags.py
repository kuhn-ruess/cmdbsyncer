"""
Checkmk Tag Syncronize
"""
import multiprocessing
from collections import Counter
from application import logger, init_db, app
from application.plugins.checkmk.cmk2 import CMK2
from application.modules.debug import ColorCodes as CC
from application.plugins.checkmk.models import CheckmkTagMngmt
from application.models.host import Host
from application.helpers.syncer_jinja import render_jinja
from application.plugins.checkmk.helpers import (
    cmk_cleanup_tag_id,
    make_progress,
    resolve_loop_list,
)


class CheckmkTagSync(CMK2):
    """
    Syncronize Checkmk Tags
    """
    groups = {}
    checkmk_group_texts = {}
    # Some hosts gave no tags in this run: a tag missing from the list then
    # says nothing, so none gets removed from Checkmk.
    tags_incomplete = False


    def _tag_worker_failed(self, name, reason):
        """A worker gave no result. Its host or rule is just left out."""
        self.tags_incomplete = True
        message = f"No tags of {name}, none gets removed in this run: {reason}"
        print(f"- ERROR: {message}")
        self.log_details.append(('error', message))

    def _collect_workers(self, pool, tasks):
        """Wait for all (name, async result) pairs and end the pool"""
        worker_timed_out = False
        for name, task in self.wait_for_tasks(tasks, app.config['PROCESS_TIMEOUT']):
            try:
                task.get(timeout=0)
            except multiprocessing.TimeoutError:
                worker_timed_out = True
                self._tag_worker_failed(name, "Timeout")
            except Exception as error:  # pylint: disable=broad-exception-caught
                if self.debug:
                    raise
                self._tag_worker_failed(name, f"{type(error).__name__}: {error}")
        self.finish_pool(pool, worker_timed_out)

    def _build_caches_one_by_one(self, db_objects, groups, mlt_expressions, advance):
        """
        Hosts run one after the other, what one host adds to the groups is
        seen by the next. A hanging worker is lost to the pool, so with
        all of them gone the remaining hosts could only wait for nothing.
        """
        process_timeout = app.config['PROCESS_TIMEOUT']
        workers = multiprocessing.cpu_count()
        with multiprocessing.Pool(workers, initializer=init_db) as pool:
            timed_out = []
            for position, entry in enumerate(db_objects):
                if sum(1 for task in timed_out if not task.ready()) >= workers:
                    self._tag_worker_failed(
                        f"the {db_objects.count() - position} remaining hosts",
                        f"All workers hang, no result for {process_timeout}s")
                    break
                task = pool.apply_async(self.build_caches,
                                        args=(entry, groups, mlt_expressions),
                                        callback=advance)
                try:
                    task.get(timeout=process_timeout)
                except multiprocessing.TimeoutError:
                    timed_out.append(task)
                    self._tag_worker_failed(entry.hostname, "Timeout")
            self.finish_pool(pool, bool(timed_out))

    def build_caches(self, db_host, groups, multiply_expressions):
        """
        Calculation of rules and Host Tags
        """
        object_attributes = self.get_attributes(db_host, 'checkmk')
        if not object_attributes:
            # An ignored host provides no tags
            return

        tags_of_host = {}
        addional_groups = {}
        do_save = False
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
                do_save = True

            tags_of_host = db_host.cache[cache_name_tags]
            addional_groups = db_host.cache[cache_name_groups]
            groups.update(addional_groups)


        cache_name = 'cmk_tags_tag_choices'
        if cache_name not in db_host.cache:
            logger.debug(" -- Build Tag Cache %s", cache_name)
            hosts_tags = self.get_tags_for_host(db_host, object_attributes,
                                                      groups, tags_of_host)
            db_host.cache[cache_name] = hosts_tags
            do_save = True
        if do_save:
            db_host.save()


    def calculate_rules(self):
        """
        Calculate needed rules
        """
        db_objects = CheckmkTagMngmt.objects(enabled=True)
        total = db_objects.count()
        with make_progress() as progress:
            task1 = progress.add_task("Calculating Needed Rules", total=total)
            manager = multiprocessing.Manager()
            base_groups = manager.dict()
            multiply_expressions = manager.list()
            with multiprocessing.Pool(initializer=init_db) as pool:
                tasks = []
                for rule in db_objects:
                    tasks.append((rule.group_id, pool.apply_async(
                        self.create_inital_groups,
                        args=(rule, base_groups, multiply_expressions),
                        callback=lambda x: progress.advance(task1))))
                self._collect_workers(pool, tasks)
        return dict(base_groups), list(multiply_expressions)


    def export_tags(self):
        """
        Export Tags to Checkmk
        """
        # pylint: disable=too-many-locals
        self.tags_incomplete = False
        base_groups, multiply_expressions = self.calculate_rules()

        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        with make_progress() as progress:
            manager = multiprocessing.Manager()
            groups = manager.dict()
            groups.update(base_groups)

            mlt_expressions = manager.list()
            mlt_expressions += multiply_expressions

            task1 = progress.add_task("Calculating Caches", total=total)
            self._build_caches_one_by_one(db_objects, groups, mlt_expressions,
                                          lambda x: progress.advance(task1))

            progress.console.print("Waiting for Calculation to finish")
            task2 = progress.add_task("Apply Hosttags to objects", total=total)
            with multiprocessing.Pool(initializer=init_db) as pool:
                tags = manager.list()
                tasks = []
                for entry in db_objects:
                    tasks.append((entry.hostname, pool.apply_async(
                        self.update_hosts_tags,
                        args=(entry, tags),
                        callback=lambda x: progress.advance(task2))))
                self._collect_workers(pool, tasks)

            progress.console.print("Waiting for Calculation to finish")
        groups = dict(groups)
        # Delete Templates
        for group_id, group in list(groups.items()):
            if group.get('is_template'):
                logger.debug("Delete Template %s", group_id)
                del groups[group_id]

        tags = list(set(tags))
        self.sync_to_checkmk(groups, tags)

    def update_hosts_multigroups(self, db_host, groups):
        """
        Update the groups ob
        """
        db_host.reload()
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
        db_host.reload()
        cache_name = 'cmk_tags_tag_choices'
        if cache_name not in db_host.cache:
            # Not existing Cache normaly can not happen
            return
        hosts_tags = db_host.cache[cache_name]

        for group_id, tags in hosts_tags.items():
            logger.debug("Check Group %s with %s", group_id, tags)
            tag_id, tag_title = tags
            tag_tuple = (group_id, tag_id, tag_title)
            if tag_tuple not in global_tags:
                logger.debug(" - Add %s", tag_tuple)
                global_tags.append(tag_tuple)

    def create_inital_groups(self, rule, groups, multiply_expressions):
        """
        Create inital group Object
        """
        logger.debug("Get Rule %s", rule.group_id)
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
        # pylint: disable=too-many-locals

        tags_of_host = {}
        addional_groups = {}

        data = object_attributes['all']
        for group_id_org, expression in multiply_expressions:
            try:
                # Same spellings as the Setup rules' loop field: a plain
                # attribute name, or Jinja rendering to a list literal or
                # a comma separated string.
                new_choices, error = resolve_loop_list(expression, data)
                if error:
                    logger.debug(" --- Loop list error: %s", error)
                    continue
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
            except Exception:  # pylint: disable=broad-exception-caught
                # The expressions come from the user; any rendering error
                # just means this group does not apply to the host.
                continue
        return tags_of_host, addional_groups

    def get_tags_for_host(self, db_object, object_attributes,
                                groups, tags_of_host):
        """
        Search all tags which this Host can provide
        """
        hostname = db_object.hostname
        tags = {}
        logger.info("Update Tags from %s", hostname)
        logger.debug("%s %s", groups, tags_of_host)


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
                        logger.debug(" --- Not matching object filter: %s", object_filter)
                        continue


                try:
                    rewrite_id = group_data['rw_id']
                    rewrite_title = group_data['rw_title']

                    new_tag_id = render_jinja(rewrite_id, **object_attributes['all'])
                    new_tag_id = new_tag_id.strip()



                    if new_tag_id:
                        new_tag_id = cmk_cleanup_tag_id(new_tag_id)

                    new_tag_title = render_jinja(rewrite_title, **object_attributes['all'])
                    new_tag_title.strip()
                except Exception as exp:  # pylint: disable=broad-exception-caught
                    logger.debug("Exception: %s", exp)
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
        self.checkmk_group_texts = {}
        for group in response[0]['value']:
            checkmk_ids[group['id']] = group['extensions']['tags']
            # A version not sending a field can't be compared on it
            texts = {key: group['extensions'][key] for key in ('topic', 'help')
                     if key in group['extensions']}
            texts['title'] = group.get('title')
            self.checkmk_group_texts[group['id']] = texts
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
        id_field = self._tag_id_field()
        found_ids = []
        tags = []
        for x, y in config_tags:
            if x:
                x = x.strip()
            y = y.strip()
            if not y:
                continue
            if x in found_ids:
                continue
            tags.append({id_field: x, 'title': y})
            found_ids.append(x)

        if not tags or len(tags) == 0:
            logger.debug("%s *%s Group has no tags", CC.WARNING, CC.ENDC)
            return False
        return self.unique_titles(tags, id_field)

    @staticmethod
    def unique_titles(tags, id_field):
        """
        Keep the title of every tag of a group unique.

        Checkmk detects renamed tags by their title. Two tags sharing one title
        therefore look like a rename of a tag which is in use, and Checkmk then
        refuses the update of the whole group unless it is repaired.

        Every tag of a duplicated title gets the id added, not only the second
        one. Would one of them keep the title, Checkmk would still read that as
        the rename of the other one and move the hosts and rules which use it.
        A title none of them carries any more is simply gone for Checkmk, and
        since all ids stay, nothing is renamed and nothing is removed.
        """
        counted = Counter(x['title'] for x in tags)
        doubled = {x for x, y in counted.items() if y > 1}
        for tag in tags:
            if tag['title'] in doubled:
                logger.debug("Tag title '%s' used twice, adding id '%s' to it",
                             tag['title'], tag[id_field])
                tag['title'] = f"{tag['title']} ({tag[id_field]})"
        return tags

    def _group_texts_differ(self, group_id, payload):
        """
        Whether the title, topic or help of a group differ from Checkmk
        """
        texts = self.checkmk_group_texts.get(group_id, {})
        return any((payload.get(key) or '') != (value or '') for key, value in texts.items())

    def _tag_id_field(self):
        """
        Field name for a host tag group id and its tag choices. Checkmk renamed
        it from ``ident`` to ``id`` in 2.4, so 2.4+ use ``id`` and 2.3 and older
        use ``ident`` (verified against 2.3.0p48, 2.4.0p19 and 2.5.0p8).
        """
        return 'id' if self.version_at_least(2, 4) else 'ident'

    def sync_to_checkmk(self, groups, tag_group_list):
        """
        Use generated configuration to Sync
        Everhting to Checkmk
        """
        # pylint: disable=too-many-locals,too-many-branches
        etag, checkmk_ids = self.get_checkmk_tags()

        create_url = "/domain-types/host_tag_group/collections/all"
        logger.debug("All Groups: %s", groups)
        with make_progress() as progress:
            task1 = progress.add_task("Sending to Checkmk", total=len(groups))
            # Checkmk renamed the tag group id field 'ident' -> 'id' in 2.4.
            id_field = self._tag_id_field()
            for syncer_group_id, syncer_group_data in groups.items():
                payload = syncer_group_data.copy()
                for what in ['object_filter', 'rw_id', 'is_template',
                             'rw_title', 'multiply_list']:
                    if what in payload:
                        del payload[what]
                # The group is built with an 'ident' key internally; send it
                # under the field name this Checkmk version expects.
                payload[id_field] = payload.pop('ident')

                tag_list = [(x[1], x[2]) for x in tag_group_list if x[0] == syncer_group_id]
                if tags := self.prepare_tags_for_checkmk(tag_list):
                    payload['tags'] = tags
                else:
                    progress.update(task1, advance=1)
                    continue
                if syncer_group_id not in checkmk_ids:
                    # Create the group
                    self.request(create_url, method="POST", data=payload)
                    progress.console.print(f" * Group {syncer_group_id} created.")
                else:
                    self.update_tag_group(progress, syncer_group_id, payload,
                                          checkmk_ids[syncer_group_id], etag)
                progress.update(task1, advance=1)

    @staticmethod
    def _merge_existing_tags(syncer_tags, checkmk_tags_flat, id_field):
        """
        Keep the tags which only exist in Checkmk, ours win on the same id
        """
        found = set()
        new_tags = []
        for tag in syncer_tags + checkmk_tags_flat:
            if tag[id_field] not in found:
                found.add(tag[id_field])
                new_tags.append(tag)
        return sorted(new_tags, key=lambda x: str(x[id_field]))

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def update_tag_group(self, progress, syncer_group_id, payload, checkmk_tags, etag):
        """
        Update one existing Tag Group in Checkmk, if it differs from ours
        """
        id_field = self._tag_id_field()
        checkmk_tags_flat = \
                [{id_field: x['id'], 'title': x['title']} \
                for x in checkmk_tags if x['title'].strip()]

        if app.config['CMK_DONT_DELETE_TAGS'] or self.tags_incomplete:
            # In this case, we merge only the new dicts into the existing ones.
            # A tag which only exists in Checkmk can carry the title of one of
            # ours, so the titles have to be checked again after the merge.
            payload['tags'] = self.unique_titles(
                self._merge_existing_tags(payload['tags'], checkmk_tags_flat, id_field),
                id_field)
        checkmk_tags_frozen = {frozenset(d.items()) for d in checkmk_tags_flat}
        syncer_tags_frozen = {frozenset(d.items()) for d in payload['tags']}
        if checkmk_tags_frozen == syncer_tags_frozen \
                and not self._group_texts_differ(syncer_group_id, payload):
            progress.console.print(f" * Group {syncer_group_id} already up to date.")
            return

        logger.debug("NEED TO UPDATE TAGS")
        logger.debug("Checkmk Tags: %s", checkmk_tags_frozen)
        logger.debug("Syncer Tags: %s", syncer_tags_frozen)
        url = f"/objects/host_tag_group/{syncer_group_id}"
        update_headers = {
            'if-match': etag
        }
        del payload[id_field]
        payload['repair'] = bool(app.config['CMK_TAG_REPAIR'])
        try:
            self.request(
                url, method="PUT", data=payload,
                additional_header=update_headers)
        except Exception as error:  # pylint: disable=broad-exception-caught
            progress.console.print(f" ! Group {syncer_group_id} can't be updated.")
            if 'repair' in str(error):
                progress.console.print(
                    "   Checkmk asks for permission to update the objects "
                    "which use this group. Set CMK_TAG_REPAIR = True to give it.")
            logger.debug(error)
        else:
            progress.console.print(f" - Group {syncer_group_id} updated.")
