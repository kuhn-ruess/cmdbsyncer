#!/usr/bin/env python3
"""
JSON Plugin
"""
#pylint: disable=too-many-arguments, logging-fstring-interpolation
import json
import ast
from requests.exceptions import JSONDecodeError
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
import click


from application import app, logger
from application.models.host import Host
from application.modules.plugin import Plugin, ResponseDataException
from application.modules.debug import ColorCodes
from application.helpers.cron import register_cronjob
from application.helpers.inventory import run_inventory


class RestImport(Plugin):
    """
    Import Plugin for Rest APIs
    and JSON Files
    """

    def get_by_http(self):
        """
        Get Json Data by HTTP
        """
        headers = {}
        auth = None
        if self.config.get('request_headers'):
            headers = ast.literal_eval(self.config['request_headers'])
            logger.debug(f"Request Headers: {headers}")


        auth = None
        if auth_type:= self.config.get('auth_type'):
            if auth_type.lower() == "basic":
                auth = HTTPBasicAuth(self.config['username'], self.config['password'])
            if auth_type.lower() == 'digest':
                auth = HTTPDigestAuth(self.config['username'], self.config['password'])

        cert = self.config.get('cert')


        params = {
            'method': self.config.get('method', 'GET'),
            'url': self.config['address'],
            'headers': headers,
        }

        if params['method'].lower() == 'post':
            params['data'] = self.config.get('post_body', {})

        if auth:
            params['auth'] = auth
        if cert:
            params['cert'] = cert

        response = self.inner_request(**params)
        try:
            return response.json()
        except JSONDecodeError as error:
            raise ResponseDataException(f"{response.text}\n Response is no valid JSON!") from error

    def get_from_file(self):
        """
        Get Json Data by File
        """
        json_path = self.config['path']
        with open(json_path, newline='', encoding='utf-8') as json_file:
            data = json.load(json_file)
            return data
        return []

    def import_hosts(self, data):
        """
        Import Hosts
        """
        if self.config.get('data_key'):
            data = data[self.config['data_key']]

        for entry in data:
            hostname = entry[self.config['hostname_field']]
            if not hostname:
                continue
            del entry[self.config['hostname_field']]
            if 'rewrite_hostname' in self.config and self.config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname, self.config['rewrite_hostname'], entry)

            print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
            host_obj = Host.get_host(hostname)
            host_obj.update_host(entry)

            do_save = host_obj.set_account(account_dict=self.config)

            if do_save:
                host_obj.save()

    def inventorize_objects(self, data):
        """
        Inventorize Hosts
        """
        if self.config.get('data_key'):
            data = data[self.config['data_key']]
        hostname_field = self.config['hostname_field']
        run_inventory(self.config, [(x[hostname_field], x) for x in \
                                    data if x[hostname_field]])


def import_hosts_json(account, debug=False):
    """
    Inner Function for Import JSON Data
    """
    json_data = RestImport(account)
    json_data.debug = debug
    json_data.name = f"Import data from {account}"
    json_data.source = "json_file_import"
    data = json_data.get_from_file()
    json_data.import_hosts(data)

def import_hosts_rest(account, debug=False):
    """
    Inner Function for Import JSON Data
    """
    json_data = RestImport(account)
    json_data.debug = debug
    json_data.name = f"Import data from {account}"
    json_data.source = "rest_api_import"
    data = json_data.get_by_http()
    json_data.import_hosts(data)

def inventorize_hosts_rest(account, debug=False):
    """
    Inner Function for Inventorize Rest APIS
    """
    json_data = RestImport(account)
    json_data.debug = debug
    json_data.name = f"Inventorize data from {account}"
    json_data.source = "rest_api_inventorize"
    data = json_data.get_by_http()
    json_data.inventorize_objects(data)


@app.cli.group(name='json')
def _cli_json():
    """JSON File Import/ Inventorize"""

@_cli_json.command('import_hosts')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def import_hosts(account, debug):
    """
    ## Import Hosts from JSON File
    """
    #pylint: disable=no-member, consider-using-generator
    import_hosts_json(account, debug)


@app.cli.group(name='rest')
def _cli_rest():
    """REST API related Commands"""


@_cli_rest.command('import_hosts')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_import_hosts_rest(account, debug):
    """
    Import Json direct from Rest API
    """
    return import_hosts_rest(account, debug)

@_cli_rest.command('inventorize_objects')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_inventorize_hosts_rest(account, debug):
    """
    Import Json direct from Rest API
    """
    return inventorize_hosts_rest(account, debug)

register_cronjob('REST API: Import Objects', import_hosts_rest)
register_cronjob('REST API: Inventorize Objects', inventorize_hosts_rest)
register_cronjob('JSON FILE: Import Hosts', import_hosts_json)
