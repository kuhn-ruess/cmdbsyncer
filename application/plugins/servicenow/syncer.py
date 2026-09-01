"""
Import objects from ServiceNow
"""
from requests.exceptions import RequestException
from requests.auth import HTTPBasicAuth
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from application.helpers.inventory import run_inventory
from application.models.host import Host
from application.modules.debug import ColorCodes as CC
from application.modules.plugin import Plugin


class ServiceNowError(Exception):
    """Raised on ServiceNow API errors."""


# How many records are read before the spinner says so again. A table of
# a large instance has hundreds of thousands of them, so the update must
# not cost anything per record.
PROGRESS_STEP = 500

# How many sys_ids one narrowed read asks for. They travel in the URL of
# a GET, so the list has to stay short enough for every gateway in front
# of the instance to pass it on.
SYS_ID_CHUNK = 50


def read_progress():
    """
    The spinner a paged read runs under. The Table API never says how
    many records are still to come, so there is no total to count to —
    what the spinner shows is that the read is still going.
    """
    return Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn())


# Headers ServiceNow answers a throttled request with. They also travel
# on a successful answer, which is what makes a run's remaining quota
# visible before it runs out.
RATE_LIMIT_HEADERS = ('X-RateLimit-Limit', 'X-RateLimit-Remaining',
                      'X-RateLimit-Reset', 'X-RateLimit-Rule', 'Retry-After')


def rate_limit_info(response):
    """
    The rate limit headers of an answer as {header: value}, empty when
    the instance sent none.
    """
    headers = getattr(response, 'headers', None) or {}
    return {name: headers[name] for name in RATE_LIMIT_HEADERS if name in headers}


def rate_limit_hint(response):
    """
    The rate limit headers as one parenthesised line for an error
    message, empty when there are none.
    """
    info = rate_limit_info(response)
    if not info:
        return ''
    return ' (' + ', '.join(f"{name}: {value}" for name, value in info.items()) + ')'


def answer_excerpt(response, length=300):
    """
    The beginning of an answer as one readable line.

    An instance that does not answer with JSON answers with a login page
    or a proxy error instead — the start of it is what says which of the
    two it is, so it belongs in the error message.
    """
    text = ' '.join((response.text or '').split())
    if len(text) > length:
        text = text[:length] + ' …'
    return text or '(empty answer)'


# The table ServiceNow keeps its CI relationships in, and the matcher
# that says a table's records find their host through it instead of
# through a reference field of their own
RELATION_TABLE = 'cmdb_rel_ci'
RELATION_MATCH = 'rel'


def parse_inventorize_tables(value):
    """
    The tables whose records are attached to an existing host, as
    [(table, matcher)].

    Written as `table:matcher` pairs, comma separated. The matcher is
    either the field of the record that names its host, or `rel` — then
    the host is looked up in the relationship table, which is how
    ServiceNow links a CI that carries no reference of its own:

    `cmdb_ci_network_adapter:cmdb_ci, cmdb_ci_db_instance:rel`

    A malformed pair raises instead of being skipped: the list is short
    and written by hand, so a typo must not silently drop a table.
    """
    tables = []
    for part in str(value or '').split(','):
        part = part.strip()
        if not part:
            continue
        table, separator, field = part.partition(':')
        if not separator or not table.strip() or not field.strip():
            raise ServiceNowError(
                f"Invalid entry {part!r} in 'inventorize_tables', "
                f"expected 'table:field'")
        tables.append((table.strip(), field.strip()))
    return tables


class SyncServiceNow(Plugin):
    """
    ServiceNow sync options
    """

    name = "ServiceNow: Import hosts"

#   .-- Flatten a record
    @staticmethod
    def flatten_record(record, keep_empty=False):
        """
        Turn a single ServiceNow table record into a flat label dict.

        With ``sysparm_display_value=true`` every field is a plain string,
        but reference fields can still arrive as ``{"link": ..., "value":
        ...}`` dicts (e.g. when display values are off). Fold those down to
        the display value / value so labels stay simple key=value pairs.

        The import drops the fields a record leaves empty — an empty
        label has nothing to export. A query keeps them: seeing that a
        field exists but is empty on this record is exactly what answers
        why the hostname field or a query finds nothing.
        """
        labels = {}
        for key, value in record.items():
            if isinstance(value, dict):
                value = value.get('display_value', value.get('value', ''))
            if value in (None, ''):
                if not keep_empty:
                    continue
                value = ''
            labels[key] = str(value)
        return labels

#.
#   .-- One Table API request
    def table_url(self, table):
        """
        Table API endpoint of one table.

        The path in front of `/table/<name>` is configurable because the
        instance is not always talked to directly: an API gateway in
        front of it publishes the same tables under its own context path.
        An account without the field keeps the `/api/now` of a plain
        instance, an empty field puts the table straight behind the
        address.
        """
        address = self.config['address'].rstrip('/')
        api_path = (self.config.get('api_path', '/api/now') or '').strip('/')
        if api_path:
            return f"{address}/{api_path}/table/{table}"
        return f"{address}/table/{table}"

    def page_size(self):
        """
        How many records one request asks the instance for
        """
        try:
            return int(self.config.get('sysparm_limit') or 1000)
        except (TypeError, ValueError):
            return 1000

    def table_params(self, limit, offset=0, query=None, fields=None):
        """
        Query parameters of one Table API request, built from the
        account. `query` and `fields` replace the account's own ones — a
        read of the relationship table narrows itself that way.
        """
        params = {
            'sysparm_limit': limit,
            'sysparm_offset': offset,
            'sysparm_display_value': self.config.get('sysparm_display_value', 'true'),
            'sysparm_exclude_reference_link': 'true',
            # Nothing here reads the total number of records, and the
            # count query the instance does for it is what makes every
            # page of a large table slow
            'sysparm_no_count': 'true',
        }
        if query := (self.config.get('sysparm_query') if query is None else query):
            params['sysparm_query'] = query
        if fields := (self.config.get('sysparm_fields') if fields is None else fields):
            params['sysparm_fields'] = fields
        return params

    def read_page(self, table, params):
        """
        Records of one Table API request. Raises ServiceNowError with the
        reason the instance gave when the table could not be read.
        """
        auth = HTTPBasicAuth(self.config['username'], self.config['password'])
        try:
            response = self.inner_request(
                'GET', url=self.table_url(table), params=params, auth=auth,
                headers={'Accept': 'application/json'},
            )
        except RequestException as error:
            raise ServiceNowError(f"Could not reach ServiceNow: {error}") from error

        # Kept for the query view, which shows what is left of the quota
        self.last_rate_limit = rate_limit_info(response)
        limits = rate_limit_hint(response)

        if response.status_code == 429:
            raise ServiceNowError(
                f"429 from {response.url}: ServiceNow is rate limiting this account"
                f"{limits}. Wait for the reset, lower sysparm_limit so a run does "
                f"fewer requests, or raise the limit of the inbound REST rule. "
                f"Answer: {answer_excerpt(response)}")

        if response.status_code == 401:
            # The body is the difference between wrong credentials, a
            # locked user and a gateway that answers 401 while throttling
            raise ServiceNowError(
                f"401 from {response.url}: invalid login for ServiceNow — check "
                f"username, password and the roles of the user{limits}. "
                f"Answer: {answer_excerpt(response)}")

        try:
            payload = response.json()
        except ValueError as error:
            # No JSON means the request never reached the Table API: a
            # wrong instance address, a path already in the address, or
            # something in front of the instance answering instead.
            raise ServiceNowError(
                f"{response.status_code} from {response.url} — the answer is no JSON, "
                f"so nothing answers the Table API under this path. Check the address "
                f"and the API path of the account: a plain instance uses "
                f"https://instance.service-now.com with /api/now, a gateway in front "
                f"of it uses its own context path. Answer: "
                f"{answer_excerpt(response)}") from error

        if 'error' in payload:
            error_payload = payload['error']
            message = error_payload.get('message', error_payload) \
                        if isinstance(error_payload, dict) else error_payload
            detail = error_payload.get('detail') if isinstance(error_payload, dict) else ''
            raise ServiceNowError(f"{response.status_code} from {response.url}{limits}: "
                                  f"{message}{' — ' + detail if detail else ''}")

        if not response.ok:
            raise ServiceNowError(
                f"{response.status_code} from {response.url}{limits}: "
                f"{answer_excerpt(response)}")

        return payload.get('result', [])

#.
#   .-- Read one table (paged)
    def get_table(self, table, query=None, fields=None):
        """
        Yield all records of a ServiceNow table, paging through the
        Table API with sysparm_limit/sysparm_offset until exhausted.
        """
        limit = self.page_size()
        offset = 0
        while True:
            results = self.read_page(table, self.table_params(limit, offset, query, fields))
            if not results:
                break

            yield from results

            if len(results) < limit:
                break
            offset += limit

#.
#   .-- Hostname of a record
    def record_hostname(self, labels):
        """
        The hostname a record would be imported under, empty when the
        record carries no value in the hostname field of the account
        """
        hostname = labels.get(self.config.get('hostname_field') or 'name')
        if hostname and (rewrite := self.config.get('rewrite_hostname')):
            hostname = Host.rewrite_hostname(hostname, rewrite, labels)
        return hostname or ''

#.
#   .-- Relationship table
    def relation_query(self, table=None):
        """
        The encoded query that narrows the relationship table.

        Two things narrow it, and both are asked of the instance instead
        of read and thrown away here. The relation types of the account,
        and — the one that decides how long a run takes — the class of
        the table being inventorized: a relation with that class on
        neither of its ends can never be looked up, so reading it means
        paging through hundreds of thousands of rows for nothing.
        """
        conditions = []
        if types := [x.strip() for x
                     in str(self.config.get('inventorize_relation_types') or '').split(',')
                     if x.strip()]:
            conditions.append(f"type.nameIN{','.join(types)}")
        if table:
            # INSTANCEOF instead of '=': the Table API of a base table
            # answers with the records of its subclasses too, and their
            # relations have to be found the same way. The 'OR' binds to
            # the condition right in front of it, so the class matches
            # on either end while the types still have to match.
            conditions.append(f"child.sys_class_nameINSTANCEOF{table}")
            conditions.append(f"ORparent.sys_class_nameINSTANCEOF{table}")
        return '^'.join(conditions)

    def _read_relations(self, query):
        """
        Every CI of the relationship table mapped to the CIs it is
        related to, for the relations the query lets through.

        Both directions are indexed on purpose: whether the syncer's
        host stands in `parent` or in `child` depends on the relation
        type ("Contains" vs "Contained by"), and looking at both sides
        finds the partner either way — one setting less to get wrong.
        """
        index = {}
        count = 0
        with read_progress() as progress:
            task = progress.add_task(f"Reading {RELATION_TABLE}", total=None)
            # Only the two ends of a relation are used, so only they are
            # asked for: a full record of every relation is what made
            # this read take minutes on a large instance
            for record in self.get_table(RELATION_TABLE, query=query, fields='parent,child'):
                count += 1
                if count % PROGRESS_STEP == 0:
                    progress.update(task, description=f"Reading {RELATION_TABLE} "
                                                      f"({count} relations)")
                labels = self.flatten_record(record)
                parent, child = labels.get('parent'), labels.get('child')
                if not parent or not child:
                    continue
                index.setdefault(parent.lower(), set()).add(child)
                index.setdefault(child.lower(), set()).add(parent)
        print(f"{CC.OKGREEN} -- {CC.ENDC}{count} relation(s) read, "
              f"{len(index)} object(s) with a relation")
        return index

    def relation_index(self, table=None):
        """
        The relationship index used for one inventorized table, read
        once per table and then kept.

        An instance that does not answer the narrowed query the way it
        is meant to would leave every record of the table without a
        host. So an empty answer is not believed: the table is then read
        the unnarrowed way once, which is slow but never wrong.
        """
        if self._relation_index is None:
            self._relation_index = {}
        if table not in self._relation_index:
            query = self.relation_query(table)
            if query:
                print(f"{CC.OKGREEN} -- {CC.ENDC}ServiceNow: Reading {RELATION_TABLE} "
                      f"with '{query}'")
            index = self._read_relations(query)
            if not index and table:
                print(f"{CC.WARNING} -- {CC.ENDC}No relation matched — reading "
                      f"{RELATION_TABLE} without the class of {table}")
                index = self._read_relations(self.relation_query())
            self._relation_index[table] = index
        return self._relation_index[table]

#.
#   .-- Hosts of this account by their ServiceNow name
    def _load_hosts(self):
        """
        Read the hosts this account imported once, into the two indexes
        the inventorize run looks them up with: by the name ServiceNow
        knows them under, and by their sys_id.

        A relation and a reference field name the CI, while the import
        may have created the host under a different name — with the
        domain appended, for example. The CI name is on the host as the
        label the import wrote it to, so that label is what identifies
        it: `ldom-s02` finds `ldom-s02.munich-airport.de`.
        """
        if self._host_index is not None:
            return
        index = {}
        sys_ids = set()
        label = self.config.get('inventorize_host_label')
        for host in Host.objects(source_account_id=self.account_id)\
                        .only('hostname', 'labels'):
            labels = host.labels or {}
            if label and (value := labels.get(label)):
                index.setdefault(value, host.hostname)
            if sys_id := labels.get('sys_id'):
                sys_ids.add(sys_id)
        if label:
            print(f"{CC.OKGREEN} -- {CC.ENDC}{len(index)} host(s) known by their "
                  f"'{label}'")
        self._host_index = index
        self._host_sys_ids = sys_ids

    def host_index(self):
        """
        The hosts of this account by the name ServiceNow knows them under
        """
        self._load_hosts()
        return self._host_index

    def host_sys_ids(self):
        """
        The sys_ids ServiceNow knows this account's hosts under, taken
        from the label the import wrote them to
        """
        self._load_hosts()
        return self._host_sys_ids

#.
#   .-- Hosts a record belongs to
    def record_hosts(self, labels, matcher, table=None):
        """
        The hosts a record of a child table belongs to — none when it
        references nothing, more than one when a relationship puts it on
        several servers.

        The found CI name is resolved to the host the import created
        for it, see `host_index`. Only a name no host carries falls back
        to `inventorize_rewrite_parent`, which adapts it the way
        `rewrite_hostname` adapts an imported one.
        """
        if matcher == RELATION_MATCH:
            found = self.relation_index(table).get((labels.get('name') or '').lower(), set())
        else:
            found = {labels[matcher]} if labels.get(matcher) else set()

        index = self.host_index()
        rewrite = self.config.get('inventorize_rewrite_parent')
        hosts = []
        for name in sorted(found):
            # The label lookup knows the real hostname; only a CI the
            # import never created falls through to the rewrite, and
            # then run_inventory reports it as unknown
            if name in index:
                hosts.append(index[name])
            elif rewrite:
                hosts.append(Host.rewrite_hostname(name, rewrite, labels))
            else:
                hosts.append(name)
        return hosts

#.
#   .-- Attach child tables to their hosts
    def inventorize_queries(self, matcher):
        """
        The encoded queries one inventorized table is read with, and
        whether they were derived rather than configured.

        The account's own `inventorize_query` wins when it is set.
        Without it the read narrows itself to the records that reference
        one of this account's hosts, by the sys_ids ServiceNow knows
        them under: a table holds the records of every CI of the
        instance — the network adapters of every tablet sit in the same
        table as the ones of the servers — and only the ones pointing at
        a host can ever be attached to one.

        The sys_id is what the reference really holds, so this asks the
        exact question and needs nothing to be true about the CMDB's
        class hierarchy. It goes out in chunks because it travels in the
        URL of a GET.
        """
        if custom := str(self.config.get('inventorize_query') or '').strip():
            return [custom], False
        sys_ids = sorted(self.host_sys_ids())
        if matcher == RELATION_MATCH or not sys_ids:
            # A relation is narrowed on the relationship table itself,
            # and hosts imported without their sys_id cannot be asked for
            return [''], False
        return [f"{matcher}IN{','.join(sys_ids[at:at + SYS_ID_CHUNK])}"
                for at in range(0, len(sys_ids), SYS_ID_CHUNK)], True

    def _group_record(self, grouped, record, matcher, table):
        """
        Put one record under every host it belongs to. Says whether it
        found one — a record naming no CI belongs nowhere.
        """
        labels = self.flatten_record(record)
        hosts = self.record_hosts(labels, matcher, table)
        for host in hosts:
            grouped.setdefault(host, []).append(labels)
        return bool(hosts)

    def _read_table_records(self, table, matcher, queries):
        """
        The records of one table grouped under the host they belong to,
        as (grouped, records read, records naming no CI). A narrowed
        read asks for its records in more than one go, which is why this
        takes a list of queries and not one.

        A table of a large instance is read page by page, which takes
        long enough that the read runs under a spinner — without it a
        run looks like it is doing nothing.
        """
        grouped = {}
        count = 0
        without_host = 0
        # The query and the field list of the account belong to the
        # import; an inventorized table is a different table and has its
        # own, so neither is inherited here
        fields = str(self.config.get('inventorize_fields') or '').strip()
        with read_progress() as progress:
            task = progress.add_task(f"Reading {table}", total=None)
            for number, query in enumerate(queries, start=1):
                part = f" [{number}/{len(queries)}]" if len(queries) > 1 else ""
                for record in self.get_table(table, query=query, fields=fields):
                    count += 1
                    if count % PROGRESS_STEP == 0:
                        progress.update(task,
                                        description=f"Reading {table}{part} ({count} records, "
                                                    f"{len(grouped)} host(s) matched)")
                    if not self._group_record(grouped, record, matcher, table):
                        without_host += 1
        return grouped, count, without_host

    def group_table_records(self, table, matcher):
        """
        The records of one table grouped under the host they belong to.

        A derived query is not believed when it finds nothing: a
        matcher that is no reference field, or hosts imported without
        their sys_id, would otherwise silently inventorize nothing at
        all. The table is then read unnarrowed once, which is slow but
        never wrong.
        """
        if matcher == RELATION_MATCH:
            # Read before the spinner below starts: the relationship
            # table runs under a spinner of its own, and rich allows
            # only one live display at a time
            self.relation_index(table)
        queries, derived = self.inventorize_queries(matcher)
        if derived:
            print(f"{CC.OKGREEN} -- {CC.ENDC}Reading {table} for the "
                  f"{len(self.host_sys_ids())} host(s) of this account, "
                  f"in {len(queries)} request(s)")
        elif queries != ['']:
            print(f"{CC.OKGREEN} -- {CC.ENDC}Reading {table} with '{queries[0]}'")
        grouped, count, without_host = self._read_table_records(table, matcher, queries)
        if not count and derived:
            print(f"{CC.WARNING} -- {CC.ENDC}No record matched — reading {table} "
                  f"without the sys_ids of the hosts")
            grouped, count, without_host = self._read_table_records(table, matcher, [''])
        print(f"{CC.OKGREEN} -- {CC.ENDC}{count} record(s) read from {table}")
        if without_host:
            # Counted, not logged one by one: a table holds the records
            # of every CI of the instance, and a log entry per skipped
            # record let the log of a run grow without an end
            print(f"{CC.WARNING} -- {CC.ENDC}{without_host} record(s) name no CI "
                  f"in '{matcher}'")
            self.log_details.append((f'{table}_records_without_ci', without_host))
        return grouped

    def drop_unknown_hosts(self, grouped, table):
        """
        The groups whose host the Syncer really has.

        An inventorized table holds the records of every CI of the
        instance, not only of the imported ones — the network adapters
        of every phone sit in the same table as the ones of the servers.
        Asking once which of the named CIs are hosts drops the rest here
        instead of doing a database query and a line of output for each
        of them.
        """
        if not grouped or self.config.get('inventorize_match_by_domain'):
            # Then a host is found by the end of its name, so an exact
            # lookup cannot say whether it exists
            return grouped
        wanted = sorted(set(grouped) | {x.lower() for x in grouped})
        known = set(Host.objects(hostname__in=wanted).distinct('hostname'))
        found = {x: records for x, records in grouped.items()
                 if x in known or x.lower() in known}
        if unknown := sorted(set(grouped) - set(found)):
            print(f"{CC.WARNING} -- {CC.ENDC}{len(unknown)} named CI(s) have no host in "
                  f"the Syncer, e.g. {', '.join(unknown[:3])}")
            self.log_details.append((f'{table}_ci_without_host', len(unknown)))
        return found

    def inventorize_data(self):
        """
        Attach the records of the configured tables to the hosts they
        belong to, instead of importing them as hosts of their own.

        Every record becomes one numbered group of inventory attributes
        below its table's key, so a server with three network cards
        carries all three.
        """
        if not self.config.get('inventorize_key'):
            raise ServiceNowError("The account has no 'inventorize_key' set")
        tables = parse_inventorize_tables(self.config.get('inventorize_tables'))
        if not tables:
            raise ServiceNowError("The account has no table in 'inventorize_tables'")

        # The hostname rewrite of the account belongs to the import; the
        # parent name has its own, so run_inventory must not apply that
        # one on top of it
        config = dict(self.config, rewrite_hostname='')

        for table, matcher in tables:
            print(f"{CC.OKGREEN} -- {CC.ENDC}ServiceNow: Processing table {table}")
            grouped = self.drop_unknown_hosts(self.group_table_records(table, matcher), table)
            objects = [(parent, self.number_records(records))
                       for parent, records in grouped.items()]
            print(f"{CC.OKGREEN} -- {CC.ENDC}{len(objects)} host(s) matched in {table}")
            run_inventory(config, objects, sub_key=table)

    @staticmethod
    def number_records(records):
        """
        Records of one host as one flat attribute dict, every field
        prefixed with the number of the record it came from. Flat on
        purpose: a nested dict only becomes usable in rules when
        LABELS_ITERATE_FIRST_LEVEL is switched on, this shape always is.
        """
        return {f"{index}_{field}": value
                for index, labels in enumerate(records)
                for field, value in labels.items()}

#.
#   .-- Query one table
    last_rate_limit = None

    # The relationship index of every inventorized table matched
    # through it, read once per table
    _relation_index = None

    # The account's hosts by the label carrying their ServiceNow name,
    # and the sys_ids ServiceNow knows them under
    _host_index = None
    _host_sys_ids = None

    def query_table(self, table, limit=25):
        """
        Read at most `limit` records of one table the way the import reads
        them, without touching a single object of the syncer. Returns the
        request it did, what the instance said about the rate limit and
        its records as {'url':, 'params':, 'limits':, 'records':
        [{'hostname':, 'labels':}]} — the hostname is empty for records
        the import would skip.
        """
        params = self.table_params(limit)
        records = [self.flatten_record(x, keep_empty=True)
                   for x in self.read_page(table, params)]
        return {
            'url': self.table_url(table),
            'params': params,
            'limits': self.last_rate_limit or {},
            'records': [{'hostname': self.record_hostname(x), 'labels': x} for x in records],
        }

#.
#   .-- Import hosts
    def import_hosts(self):
        """
        Import objects from ServiceNow tables into the Syncer
        """
        # An empty custom field arrives as False, so it cannot be split
        tables = [x.strip() for x in (self.config.get('tables') or '').split(',') if x.strip()]
        if not tables:
            raise ServiceNowError("The account has no table in 'tables'")

        for table in tables:
            print(f"{CC.OKGREEN} -- {CC.ENDC}ServiceNow: Processing table {table}")
            count = 0

            for record in self.get_table(table):
                labels = self.flatten_record(record)

                hostname = self.record_hostname(labels)
                if not hostname:
                    self.log_details.append(('unnamed_record_skipped', table))
                    continue

                print(f"{CC.HEADER}Process Object: {hostname}{CC.ENDC}")

                host_obj = Host.get_host(hostname)
                host_obj.update_host(labels)
                do_save = host_obj.set_account(account_dict=self.config)

                if do_save:
                    host_obj.save()
                    count += 1
                else:
                    print(f"{CC.WARNING} * {CC.ENDC} Managed by different master")

            print(f"{CC.OKGREEN} -- {CC.ENDC}Imported {count} objects from {table}\n")
