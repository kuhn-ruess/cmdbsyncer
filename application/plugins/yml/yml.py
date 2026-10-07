"""
YML Plugin
"""
# pylint: disable=duplicate-code
import ast
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from application import logger
from application.helpers.inventory import run_inventory
from application.helpers.import_hostnames import get_import_hosts, update_import_host
from application.modules.plugin import Plugin, ResponseDataException
try:
    import yaml as yml
    from yaml import YAMLError
except ImportError:
    pass

from syncerapi.v1 import (
    cc,
)

class YMLSyncer(Plugin):
    """
    YML Syncer
    """


    def parse_yml(self, data):
        """
        Parse YML Data
        """
        response = []
        variables_key = self.config['name_of_variables_key']
        host_key = self.config['name_of_hosts_key']
        for _data_key, values in data.items():
            if not values.get(host_key):
                continue
            variables = values[variables_key]
            for hostname in values[host_key]:
                if not hostname:
                    continue
                host_entry = {
                    'hostname': hostname,
                }
                host_entry.update(variables)
                response.append(host_entry)
        return response

    def get_by_http(self):
        """
        Get YML File by HTTP
        """
        headers = {}
        if self.config.get('request_headers'):
            headers = ast.literal_eval(self.config['request_headers'])
            # Do not log raw headers — shared HTTP path redacts them.
            logger.debug("Request Headers: %d custom header(s) passed to shared HTTP path",
                         len(headers))


        auth = None
        if auth_type:= self.config.get('auth_type'):
            if auth_type.lower() == "basic":
                auth = HTTPBasicAuth(self.config['username'], self.config['password'])
            if auth_type.lower() == 'digest':
                auth = HTTPDigestAuth(self.config['username'], self.config['password'])

        cert = self.config.get('cert')

        params = {
            'method': 'get',
            'url': self.config['address'],
            'headers': headers,
        }

        if auth:
            params['auth'] = auth
        if cert:
            params['cert'] = cert

        response = self.inner_request(**params)
        try:
            return self.parse_yml(yml.safe_load(response.text))
        except YAMLError as error:
            raise ResponseDataException(f"{response.text}\n YML is no valid!") from error

    def get_from_file(self):
        """
        Get Json Data by File
        """
        yml_path = self.config['path']
        with open(yml_path, newline='', encoding='utf-8') as yml_file:
            try:
                data = self.parse_yml(yml.safe_load(yml_file))
                return data
            except YAMLError as error:
                raise ResponseDataException(f"{yml_file}\n YML is no valid!") from error
        return []

    def import_hosts(self, data):
        """
        Import Hosts
        """
        for entry in data:
            hostname = entry['hostname']
            if not hostname:
                continue
            del entry['hostname']
            for name, host_obj in get_import_hosts(hostname, self.config, entry):
                print(f" {cc.OKGREEN}** {cc.ENDC} Update {name}")
                update_import_host(host_obj, entry, self.config)

    def inventorize_objects(self, data):
        """
        Inventorize Hosts
        """
        entries = []
        for entry in data:
            hostname = entry.get('hostname')
            if not hostname:
                continue
            # run_inventory applies rewrite_hostname, the same way the
            # import does
            entries.append((hostname, entry))
        run_inventory(self.config, entries)


def import_hosts_yml(account, debug=False):
    """
    Inner Function for Import JSON Data
    """
    yml_data = YMLSyncer(account)
    yml_data.debug = debug
    yml_data.name = f"Import data from {account}"
    yml_data.source = "yml_file_import"
    data = yml_data.get_from_file()
    yml_data.import_hosts(data)

def import_hosts_rest(account, debug=False):
    """
    Inner Function for Import YML Data via HTTP
    """
    yml_data = YMLSyncer(account)
    yml_data.debug = debug
    yml_data.name = f"Import data from {account}"
    yml_data.source = "yml_http_import"
    data = yml_data.get_by_http()
    yml_data.import_hosts(data)

def inventorize_hosts_rest(account, debug=False):
    """
    Inner Function for Inventorize YML Data via HTTP
    """
    yml_data = YMLSyncer(account)
    yml_data.debug = debug
    yml_data.name = f"Inventorize data from {account}"
    yml_data.source = "yml_http_inventorize"
    data = yml_data.get_by_http()
    yml_data.inventorize_objects(data)

def inventorize_hosts_file(account, debug=False):
    """
    Inner Function for Inventorize YML Data from File
    """
    yml_data = YMLSyncer(account)
    yml_data.debug = debug
    yml_data.name = f"Inventorize data from {account}"
    yml_data.source = "yml_file_inventorize"
    data = yml_data.get_from_file()
    yml_data.inventorize_objects(data)
