"""
Import Jira Data
"""
import json

from syncerapi.v1 import (
    cc,
    Host,
)

from application.modules.plugin import Plugin


class JiraCloud(Plugin):
    """
    Jira Cloud Import
    """
    base_url = ""
    headers = {}
    auth = ()

    def __init__(self, account):
        """ INIT """
        super().__init__(account)

        workspace_id = self.config['workspace_id']
        self.base_url = f"https://api.atlassian.com/jsm/assets/workspace/{workspace_id}"

        self.headers = {
          "Accept": "application/json",
          "Content-Type": "application/json",
        }

        self.auth = (self.config['username'], self.config['password'])

        # Per-instance attribute cache. A class-level dict would leak
        # attribute ids/names across different Jira workspaces or
        # accounts run in the same process and write wrong field names
        # into imported hosts.
        self.name_cache = {}

    def get_name_by_id(self, obj_id):
        """
        Get name of attribute by id
        """
        if not self.name_cache:
            self.get_attribute_names()


        return self.name_cache.get(obj_id, f'unk_{obj_id}')

    def get_attribute_names(self):
        """
        Get the Names of all attributes
        """
        url = f"{self.base_url}/v1/objectschema/list"
        response = self.inner_request(method="GET", url=url,
                                      headers=self.headers, auth=self.auth)

        for schema in response.json()['values']:
            url = f"{self.base_url}/v1/objectschema/{schema['id']}/attributes"
            schema_resp = self.inner_request(method="GET", url=url,
                                          headers=self.headers, auth=self.auth)
            for attribute in schema_resp.json():
                self.name_cache[attribute['id']] = attribute['name']

    def _iter_aql_objects(self, ql_query):
        """Yield every object for ``ql_query``, following AQL pagination."""
        url = f"{self.base_url}/v1/object/aql"
        page_size = 500
        start_at = 0
        payload = json.dumps({'qlQuery': ql_query})

        while True:
            query = {
                'startAt': start_at,
                'maxResults': page_size,
            }
            response = self.inner_request(
                method="POST", url=url, params=query,
                headers=self.headers, data=payload, auth=self.auth,
            )
            body = response.json()
            if 'values' not in body:
                raise ValueError("No Data from Jira, Check your Account Settings")

            values = body['values']
            if not values:
                return
            yield from values

            if body.get('isLast'):
                return
            total = body.get('total')
            start_at += len(values)
            if total is not None and start_at >= total:
                return
            if len(values) < page_size:
                return

    def import_objects(self):
        """
        Import Objects from Jira
        """
        print(f"{cc.OKGREEN} -- {cc.ENDC}Request: Read all Hosts")

        for host in self._iter_aql_objects(self.config['ql_query']):
            hostname = host['label']
            attributes = host['attributes']
            host_obj = Host.get_host(hostname)
            id_field = 'objectTypeAttributeId'
            obj_field = 'objectAttributeValues'
            labels = {}
            for attr in attributes:
                # Skip attributes without values instead of raising an
                # IndexError and aborting the whole import.
                values = attr.get(obj_field) or []
                if not values:
                    continue
                labels[self.get_name_by_id(attr[id_field])] = values[0].get('value')

            host_obj.update_host(labels)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()

def import_jira_cloud(account, debug=False):
    """
    Import
    """

    jira = JiraCloud(account)
    jira.debug = debug
    jira.name = "Jira Cloud: Import Objects"
    jira.source = "jira_cloud_import"

    jira.import_objects()
