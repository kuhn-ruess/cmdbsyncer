"""
Import objects from ServiceNow
"""
from requests.exceptions import RequestException
from requests.auth import HTTPBasicAuth

from application.helpers.inventory import run_inventory
from application.models.host import Host
from application.modules.debug import ColorCodes as CC
from application.modules.plugin import Plugin


class ServiceNowError(Exception):
    """Raised on ServiceNow API errors."""


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

    def table_params(self, limit, offset=0, query=None):
        """
        Query parameters of one Table API request, built from the
        account. `query` replaces the account's own one — a read of the
        relationship table narrows itself that way.
        """
        params = {
            'sysparm_limit': limit,
            'sysparm_offset': offset,
            'sysparm_display_value': self.config.get('sysparm_display_value', 'true'),
            'sysparm_exclude_reference_link': 'true',
        }
        if query := (self.config.get('sysparm_query') if query is None else query):
            params['sysparm_query'] = query
        if fields := self.config.get('sysparm_fields'):
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
    def get_table(self, table, query=None):
        """
        Yield all records of a ServiceNow table, paging through the
        Table API with sysparm_limit/sysparm_offset until exhausted.
        """
        limit = self.page_size()
        offset = 0
        while True:
            results = self.read_page(table, self.table_params(limit, offset, query))
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
    def relation_query(self):
        """
        The encoded query that narrows the relationship table to the
        configured types. Filtering on the instance instead of here is
        what keeps a run from reading a relationship table of any size.
        """
        types = [x.strip() for x
                 in str(self.config.get('inventorize_relation_types') or '').split(',')
                 if x.strip()]
        return f"type.nameIN{','.join(types)}" if types else ''

    def relation_index(self):
        """
        Every CI of the relationship table mapped to the CIs it is
        related to, read once per run.

        Both directions are indexed on purpose: whether the syncer's
        host stands in `parent` or in `child` depends on the relation
        type ("Contains" vs "Contained by"), and looking at both sides
        finds the partner either way — one setting less to get wrong.
        """
        if self._relation_index is None:
            print(f"{CC.OKGREEN} -- {CC.ENDC}ServiceNow: Reading {RELATION_TABLE}")
            index = {}
            for record in self.get_table(RELATION_TABLE, query=self.relation_query()):
                labels = self.flatten_record(record)
                parent, child = labels.get('parent'), labels.get('child')
                if not parent or not child:
                    continue
                index.setdefault(parent.lower(), set()).add(child)
                index.setdefault(child.lower(), set()).add(parent)
            print(f"{CC.OKGREEN} -- {CC.ENDC}{len(index)} object(s) with a relation")
            self._relation_index = index
        return self._relation_index

#.
#   .-- Hosts of this account by their ServiceNow name
    def host_index(self):
        """
        The hosts of this account by the name ServiceNow knows them
        under, read in one query.

        A relation and a reference field name the CI, while the import
        may have created the host under a different name — with the
        domain appended, for example. The CI name is on the host as the
        label the import wrote it to, so that label is what identifies
        it: `ldom-s02` finds `ldom-s02.munich-airport.de`.
        """
        if self._host_index is None:
            index = {}
            if label := self.config.get('inventorize_host_label'):
                for host in Host.objects(source_account_id=self.account_id)\
                                .only('hostname', 'labels'):
                    if value := (host.labels or {}).get(label):
                        index.setdefault(value, host.hostname)
                print(f"{CC.OKGREEN} -- {CC.ENDC}{len(index)} host(s) known by their "
                      f"'{label}'")
            self._host_index = index
        return self._host_index

#.
#   .-- Hosts a record belongs to
    def record_hosts(self, labels, matcher):
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
            found = self.relation_index().get((labels.get('name') or '').lower(), set())
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
            grouped = {}
            for record in self.get_table(table):
                labels = self.flatten_record(record)
                hosts = self.record_hosts(labels, matcher)
                if not hosts:
                    self.log_details.append(('record_without_host', f"{table}:{matcher}"))
                    continue
                for host in hosts:
                    grouped.setdefault(host, []).append(labels)

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

    # Read once per run, and only when a table is matched through it
    _relation_index = None

    # The account's hosts by the label carrying their ServiceNow name
    _host_index = None

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
