"""
YML Plugin
"""

import ast
import click
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from application import app, logger
from application.helpers.inventory import run_inventory
from application.modules.plugin import Plugin, ResponseDataException
try:
    import yaml as yml
    from yaml import YAMLError
except ImportError:
    pass

from syncerapi.v1 import (
    register_cronjob,
    cc,
    Host
)

@app.cli.group(name='yml')
def _cli_yml():
    """YML Import"""

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
            logger.debug("Request Headers: %s", headers)


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
            if 'rewrite_hostname' in self.config and self.config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname, self.config['rewrite_hostname'], entry)

            print(f" {cc.OKGREEN}** {cc.ENDC} Update {hostname}")
            host_obj = Host.get_host(hostname)
            host_obj.update_host(entry)

            do_save = host_obj.set_account(account_dict=self.config)

            if do_save:
                host_obj.save()

    def inventorize_objects(self, data):
        """
        Inventorize Hosts
        """
        run_inventory(self.config, [(x['hostname'], x) for x in \
                                    data if x['hostname']])


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

@_cli_yml.command('import_objects')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_import_hosts_yml(account, debug):
    """
    Import Hosts from YML File
    """
    import_hosts_yml(account, debug)

@_cli_yml.command('import_objects_rest')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_import_hosts_yml_rest(account, debug):
    """
    Import Hosts from YML via HTTP
    """
    import_hosts_rest(account, debug)

@_cli_yml.command('inventorize_objects_rest')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_inventorize_hosts_yml_rest(account, debug):
    """
    Inventorize Hosts from YML via HTTP
    """
    inventorize_hosts_rest(account, debug)

@_cli_yml.command('inventorize_objects_file')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_inventorize_hosts_yml_file(account, debug):
    """
    Inventorize Hosts from YML File
    """
    inventorize_hosts_file(account, debug)

register_cronjob('YML FILE: Import Hosts', import_hosts_yml)
register_cronjob('YML HTTP: Import Hosts', import_hosts_rest)
register_cronjob('YML HTTP: Inventorize Objects', inventorize_hosts_rest)
register_cronjob('YML FILE: Inventorize Objects', inventorize_hosts_file)
