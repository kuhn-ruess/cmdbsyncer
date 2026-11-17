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
from application.helpers.syncer_jinja import render_jinja
from application.helpers.import_hostnames import get_import_hosts, update_import_host


class RestImport(Plugin):
    """
    Import Plugin for Rest APIs
    and JSON Files
    """

    def get_by_http(self, page=None):
        """
        Get Json Data by HTTP

        ``page`` maps the offset and limit field names of the account to
        the values of the page to fetch: a GET sends them as query
        parameters, a POST adds them to the top level of its JSON body.
        """
        page = page or {}
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
            body = self.config.get('post_body')
            if body:
                # Jinja, e.g. to build the body from a lookup table
                body = render_jinja(body, mode='raise', replace_newlines=False)
            if page:
                body = self._add_page_to_body(body, page)
            params['data'] = body or {}
        elif page:
            params['params'] = page

        if auth:
            params['auth'] = auth
        if cert:
            params['cert'] = cert

        response = self.inner_request(**params)
        try:
            return response.json()
        except JSONDecodeError as error:
            raise ResponseDataException(f"{response.text}\n Response is no valid JSON!") from error

    @staticmethod
    def _add_page_to_body(body, page):
        """The JSON body with the paging fields set on its top level."""
        try:
            data = json.loads(body or '{}')
        except ValueError as error:
            raise ValueError(f"post_body is no valid JSON, paging can't be added: {error}") \
                from error
        if not isinstance(data, dict):
            raise ValueError("post_body has to be a JSON object to add the paging fields")
        data.update(page)
        return json.dumps(data)

    def get_from_file(self):
        """
        Get Json Data by File
        """
        json_path = self.config['path']
        with open(json_path, newline='', encoding='utf-8') as json_file:
            data = json.load(json_file)
            return data
        return []

    def _records(self, data):
        """The records of one response, below ``data_key`` if set."""
        if self.config.get('data_key'):
            return data[self.config['data_key']]
        return data

    def _get_pages(self, page_limit):
        """
        The records of every page: the request carries the offset (records
        to skip) and the limit until a page brings less than ``page_limit``
        records.
        """
        offset_field = self.config.get('page_offset_field') or 'offset'
        limit_field = self.config.get('page_limit_field') or 'limit'
        records = []
        previous = None
        offset = 0
        while True:
            page = self._records(self.get_by_http({offset_field: offset,
                                                   limit_field: page_limit}))
            # An API that does not page would be asked forever
            if len(page) > page_limit or (page and page == previous):
                raise ResponseDataException(
                    f"The API ignores the paging fields '{offset_field}' and "
                    f"'{limit_field}', check page_offset_field and page_limit_field")
            records.extend(page)
            if len(page) < page_limit:
                return records
            previous = page
            offset += page_limit

    def _filter(self, records):
        """
        Only the records whose ``filter_field`` has a value found in the
        first column of the lookup table ``filter_lookup_table``.
        """
        field = self.config.get('filter_field')
        table = self.config.get('filter_lookup_table')
        if not field and not table:
            return records
        if not field or not table:
            raise ValueError("Set both filter_field and filter_lookup_table, or none")
        # pylint: disable-next=import-outside-toplevel
        from application.helpers.lookup_table import lookup_keys
        keys = lookup_keys(table)
        if keys is None:
            raise ValueError(f"Lookup table '{table}' not found")
        kept = [record for record in records
                if record.get(field) is not None and str(record[field]).strip() in keys]
        print(f" {ColorCodes.OKBLUE}** {ColorCodes.ENDC} Filter on {field}: "
              f"{len(kept)} of {len(records)} records match lookup table {table}")
        return kept

    def get_records(self):
        """
        The records to import: from the file or the API, page by page
        when the account sets a ``page_limit``, then filtered.
        """
        if self.config.get('path'):
            records = self._records(self.get_from_file())
        elif page_limit := int(self.config.get('page_limit') or 0):
            records = self._get_pages(page_limit)
        else:
            records = self._records(self.get_by_http())
        return self._filter(records)

    def import_hosts(self, data):
        """
        Import Hosts from the records of get_records()
        """
        for entry in data:
            hostname = entry.pop(self.config['hostname_field'], None)
            if not hostname:
                continue
            for name, host_obj in get_import_hosts(hostname, self.config, entry):
                print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {name}")
                update_import_host(host_obj, entry, self.config)

    def inventorize_objects(self, data):
        """
        Inventorize Hosts from the records of get_records()
        """
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



def import_hosts_rest(account, debug=False):
    """
    Inner Function for Import JSON Data
    """
    json_data = RestImport(account)
    json_data.debug = debug
    json_data.name = f"Import data from {account}"
    json_data.source = "rest_api_import"
    data = json_data.get_records()
    json_data.import_hosts(data)

def inventorize_hosts_rest(account, debug=False):
    """
    Inner Function for Inventorize Rest APIS
    """
    json_data = RestImport(account)
    json_data.debug = debug
    json_data.name = f"Inventorize data from {account}"
    json_data.source = "rest_api_inventorize"
    data = json_data.get_records()
    json_data.inventorize_objects(data)
