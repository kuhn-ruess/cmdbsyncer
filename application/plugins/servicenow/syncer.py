"""
Import objects from ServiceNow
"""
from requests.exceptions import RequestException
from requests.auth import HTTPBasicAuth

from application.models.host import Host
from application.modules.debug import ColorCodes as CC
from application.modules.plugin import Plugin


class ServiceNowError(Exception):
    """Raised on ServiceNow API errors."""


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


class SyncServiceNow(Plugin):
    """
    ServiceNow sync options
    """

    name = "ServiceNow: Import hosts"

#   .-- Flatten a record
    @staticmethod
    def flatten_record(record):
        """
        Turn a single ServiceNow table record into a flat label dict.

        With ``sysparm_display_value=true`` every field is a plain string,
        but reference fields can still arrive as ``{"link": ..., "value":
        ...}`` dicts (e.g. when display values are off). Fold those down to
        the display value / value so labels stay simple key=value pairs.
        """
        labels = {}
        for key, value in record.items():
            if isinstance(value, dict):
                value = value.get('display_value', value.get('value', ''))
            if value in (None, ''):
                continue
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

    def table_params(self, limit, offset=0):
        """
        Query parameters of one Table API request, built from the account
        """
        params = {
            'sysparm_limit': limit,
            'sysparm_offset': offset,
            'sysparm_display_value': self.config.get('sysparm_display_value', 'true'),
            'sysparm_exclude_reference_link': 'true',
        }
        if query := self.config.get('sysparm_query'):
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

        if response.status_code == 401:
            raise ServiceNowError(
                "Invalid login for ServiceNow, check username/password and roles")

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
            raise ServiceNowError(f"{response.status_code} from {response.url}: {message}"
                                  f"{' — ' + detail if detail else ''}")

        if not response.ok:
            raise ServiceNowError(
                f"{response.status_code} from {response.url}: {answer_excerpt(response)}")

        return payload.get('result', [])

#.
#   .-- Read one table (paged)
    def get_table(self, table):
        """
        Yield all records of a ServiceNow table, paging through the
        Table API with sysparm_limit/sysparm_offset until exhausted.
        """
        limit = self.page_size()
        offset = 0
        while True:
            results = self.read_page(table, self.table_params(limit, offset))
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
#   .-- Query one table
    def query_table(self, table, limit=25):
        """
        Read at most `limit` records of one table the way the import reads
        them, without touching a single object of the syncer. Returns the
        request it did and its records as
        {'url':, 'params':, 'records': [{'hostname':, 'labels':}]} — the
        hostname is empty for records the import would skip.
        """
        params = self.table_params(limit)
        records = [self.flatten_record(x) for x in self.read_page(table, params)]
        return {
            'url': self.table_url(table),
            'params': params,
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
