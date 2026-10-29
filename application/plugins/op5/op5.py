"""
Import Hosts from OP5 Monitor

Reads the hosts through the filter API of OP5 Monitor:
GET /api/filter/query?query=[hosts] all&columns=...&format=json

API Output (one entry per host):
[{'name': 'web01',
  'alias': 'Webserver 01',
  'display_name': 'web01',
  'address': '10.0.0.1',
  'groups': ['linux', 'web'],
  'contacts': ['admin'],
  'contact_groups': ['linux-admins'],
  'parents': ['switch01'],
  'notes': '',
  'custom_variables': {'LOCATION': 'Berlin'}}]
"""
from syncerapi.v1 import (
    cc,
)

from application.modules.plugin import Plugin
from application.helpers.inventory import run_inventory
from application.helpers.import_hostnames import get_import_hosts, update_import_host

DEFAULT_COLUMNS = [
    "name", "alias", "display_name", "address", "groups", "contacts",
    "contact_groups", "parents", "notes", "custom_variables",
]


class Op5(Plugin):
    """
    OP5 Monitor Import
    """
    page_size = 1000

    def columns(self):
        """
        Columns to request, the account field `columns` overrides the default.
        The hostname column `name` is always part of the request.
        """
        configured = [x.strip() for x in self.config.get('columns', '').split(',')
                      if x.strip()]
        columns = configured or list(DEFAULT_COLUMNS)
        if 'name' not in columns:
            columns.insert(0, 'name')
        return columns

    @staticmethod
    def prepare_attributes(host):
        """
        Flatten the custom variables of a host into own attributes,
        so they can be used like every other attribute.
        """
        attributes = dict(host)
        custom_variables = attributes.pop('custom_variables', None)
        if isinstance(custom_variables, dict):
            for key, value in custom_variables.items():
                attributes[f'custom_variable_{key.lower()}'] = value
        return attributes

    def get_hosts(self):
        """
        Return Hostname and Attributes of every host, paging through the API
        """
        url = f"{self.config['address'].rstrip('/')}/api/filter/query"
        auth = (self.config['username'], self.config['password'])
        print(f"{cc.OKGREEN} -- {cc.ENDC}Request: Read all Hosts")

        offset = 0
        while True:
            params = {
                "query": "[hosts] all",
                "columns": ",".join(self.columns()),
                "format": "json",
                "limit": str(self.page_size),
                "offset": str(offset),
            }
            response = self.inner_request(method="GET", url=url, params=params, auth=auth)
            hosts = response.json()
            if not isinstance(hosts, list):
                raise ValueError(f"Unexpected answer from OP5: {hosts}")
            for host in hosts:
                yield host['name'], self.prepare_attributes(host)

            if len(hosts) < self.page_size:
                return
            offset += len(hosts)

    def import_objects(self):
        """
        Import Hosts from OP5
        """
        for hostname, attributes in self.get_hosts():
            for name, host_obj in get_import_hosts(hostname, self.config, attributes):
                print(f" {cc.OKGREEN}** {cc.ENDC} Update {name}")
                update_import_host(host_obj, attributes, self.config)

    def inventorize_objects(self):
        """
        Inventorize OP5 Hosts
        """
        run_inventory(self.config, self.get_hosts())

def import_op5(account, debug=False):
    """
    Import
    """
    op5 = Op5(account)
    op5.debug = debug
    op5.name = "OP5 Monitor: Import Hosts"
    op5.source = "op5_import"

    op5.import_objects()

def inventorize_op5(account, debug=False):
    """
    Inventorize
    """
    op5 = Op5(account)
    op5.debug = debug
    op5.name = "OP5 Monitor: Inventorize Hosts"
    op5.source = "op5_inventorize"

    op5.inventorize_objects()
