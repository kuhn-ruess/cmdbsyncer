#!/usr/bin/env python3
"""
JSON Plugin
"""
# pylint: disable=duplicate-code
import json
import ast
from requests.exceptions import JSONDecodeError
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from application import logger
from application.modules.plugin import Plugin, ResponseDataException
from application.modules.debug import ColorCodes
from application.helpers.inventory import run_inventory
from application.helpers.import_hostnames import get_import_hosts, update_import_host


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
            for name, host_obj in get_import_hosts(hostname, self.config, entry):
                print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {name}")
                update_import_host(host_obj, entry, self.config)

    def inventorize_objects(self, data):
        """
        Inventorize Hosts
        """
        if self.config.get('data_key'):
            data = data[self.config['data_key']]
        hostname_field = self.config['hostname_field']
        entries = []
        for entry in data:
            hostname = entry.get(hostname_field)
            if not hostname:
                continue
            # run_inventory applies rewrite_hostname, the same way the
            # import does
            entries.append((hostname, entry))
        run_inventory(self.config, entries)



def _fetch_rest_data(importer):
    """Choose HTTP vs local file depending on account configuration."""
    if importer.config.get('path'):
        return importer.get_from_file()
    return importer.get_by_http()


def import_hosts_rest(account, debug=False):
    """
    Inner Function for Import JSON Data
    """
    json_data = RestImport(account)
    json_data.debug = debug
    json_data.name = f"Import data from {account}"
    json_data.source = "rest_api_import"
    data = _fetch_rest_data(json_data)
    json_data.import_hosts(data)

def inventorize_hosts_rest(account, debug=False):
    """
    Inner Function for Inventorize Rest APIS
    """
    json_data = RestImport(account)
    json_data.debug = debug
    json_data.name = f"Inventorize data from {account}"
    json_data.source = "rest_api_inventorize"
    data = _fetch_rest_data(json_data)
    json_data.inventorize_objects(data)
