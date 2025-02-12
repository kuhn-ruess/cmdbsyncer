"""
Import Jira Data
"""
#pylint: disable=too-many-locals
import json
import click
from syncerapi.v1 import (
    register_cronjob,
    cc,
    Host,
)

from application.plugins.jira import jira_cli
from application.modules.plugin import Plugin

class JiraCloud(Plugin):
    """
    Jira Cloud Import
    """
    base_url = ""
    headers = {}
    auth = ()
    name_cache = {}

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

    def get_id(self, obj_id):
        """
        Get ID of Object and Cache items
        """

        if obj_id not in self.name_cache:
            url = f"{self.base_url}/v1/objecttype/{obj_id}"
            response = self.inner_request(method="GET", url=url,
                                          headers=self.headers, auth=self.auth)
            resp_json = response.json()
            obj_name = resp_json.get('name', f'not_found_{obj_id}')
            self.name_cache[obj_id] = obj_name
        else:
            obj_name = self.name_cache[obj_id]
        return obj_name

    def import_objects(self):
        """
        Import Objects from Jira
        """

        url = f"{self.base_url}/v1/object/aql"
        print(f"{cc.OKGREEN} -- {cc.ENDC}Request: Read all Hosts")

        query = {
            'startAt': 1,
            'maxResults': 10000, #@TODO Pagination
        }

        payload = json.dumps({
            'qlQuery' : self.config['ql_query'],
        })
        # We send data on purpose (not json)
        response = self.inner_request(method="POST", url=url, params=query,
                                      headers=self.headers, data=payload, auth=self.auth)

        all_data = response.json()
        if 'values' not in all_data:
            raise ValueError("No Data from Jira, Check your Account Settings")
        for host in all_data['values']:
            hostname = host['label']
            attributes = host['attributes']
            host_obj = Host.get_host(hostname)
            id_field = 'globalId'
            obj_field = 'objectAttributeValues'
            labels = \
                    {self.get_id(x[id_field]):x[obj_field][0].get('value') \
                    for x in attributes}

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

@jira_cli.command('import_cloud')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_import_jira(account, debug):
    """
    Import from Cloud Instance
    """
    try:
        import_jira_cloud(account, debug)
    except Exception as error:
        if debug:
            raise
        print(f"Error: {error}")

register_cronjob('Jira Cloud: Import  Hosts', import_jira_cloud)
