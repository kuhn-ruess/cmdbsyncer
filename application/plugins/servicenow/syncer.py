"""
Import objects from ServiceNow
"""
from requests.auth import HTTPBasicAuth

from application.models.host import Host
from application.modules.debug import ColorCodes as CC
from application.modules.plugin import Plugin


class ServiceNowError(Exception):
    """Raised on ServiceNow API errors."""


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
#   .-- Read one table (paged)
    def get_table(self, table):
        """
        Yield all records of a ServiceNow table, paging through the
        Table API with sysparm_limit/sysparm_offset until exhausted.
        """
        address = self.config['address'].rstrip('/')
        url = f"{address}/api/now/table/{table}"
        auth = HTTPBasicAuth(self.config['username'], self.config['password'])

        try:
            limit = int(self.config.get('sysparm_limit') or 1000)
        except (TypeError, ValueError):
            limit = 1000

        offset = 0
        while True:
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

            response = self.inner_request(
                'GET', url=url, params=params, auth=auth,
                headers={'Accept': 'application/json'},
            )

            if response.status_code == 401:
                raise ServiceNowError(
                    "Invalid login for ServiceNow, check username/password and roles")

            payload = response.json()
            if 'error' in payload:
                raise ServiceNowError(payload['error'].get('message', payload['error']))

            results = payload.get('result', [])
            if not results:
                break

            yield from results

            if len(results) < limit:
                break
            offset += limit

#.
#   .-- Import hosts
    def import_hosts(self):
        """
        Import objects from ServiceNow tables into the Syncer
        """
        hostname_field = self.config.get('hostname_field', 'name')
        rewrite = self.config.get('rewrite_hostname')

        tables = [x.strip() for x in self.config.get('tables', '').split(',') if x.strip()]

        for table in tables:
            print(f"{CC.OKGREEN} -- {CC.ENDC}ServiceNow: Processing table {table}")
            count = 0

            for record in self.get_table(table):
                labels = self.flatten_record(record)

                hostname = labels.get(hostname_field)
                if not hostname:
                    self.log_details.append(('unnamed_record_skipped', table))
                    continue

                if rewrite:
                    hostname = Host.rewrite_hostname(hostname, rewrite, labels)

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
