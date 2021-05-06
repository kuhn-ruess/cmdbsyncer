
"""
Add Hosts into CMK Version 2 Installations
"""
import json
import click
import requests
from application import app, log
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.helpers.get_action import GetAction

class CmkException(Exception):
    """Cmk Errors"""

class UpdateCMKv2():
    """
    Get Data from CMK
    """

    def __init__(self, config):
        """
        Inital
        """
        self.log = log
        self.config = config
        self.account_id = str(config['_id'])
        self.account_name = config['name']
        self.action_helper = GetAction()

    def request(self, params, method='GET', data=None, additional_header=None):
        """
        Handle Request to CMK
        """
        address = self.config['address']
        username = self.config['username']
        password = self.config['password']
        url = f'{address}/check_mk/api/1.0/{params}'
        headers = {
            'Authorization': f"Bearer {username} {password}"
        }
        if additional_header:
            headers.update(additional_header)

        method = method.lower()
        if method == 'get':
            response = requests.get(url, headers=headers, verify=False)
        elif method == 'post':
            response = requests.post(url, data=data, headers=headers, verify=False)
        elif method == 'put':
            headers['content-type'] = 'application/json'
            headers['Accept'] = 'application/json'
            response = requests.put(url, json=data, headers=headers, verify=False)
        elif method == 'delete':
            response = requests.delete(url, headers=headers, verify=False)

        if response.status_code != 200:
            print(response.json())
            raise CmkException(response.json()['title'])
        return response.json(), response.headers

    def run(self):
        """Run Actual Job"""
        for db_host in Host.objects():
            # Check if Host Exists
            need_update = False
            url = f"objects/host_config/{db_host.hostname}"
            cmk_host, headers = self.request(url, "GET")


            host_etag = headers['ETag']

            # compare Labels
            db_labels = db_host.get_labels()
            cmk_labels = cmk_host['extensions']['attributes'].get('labels', {})

            applied_labels = {}


            next_actions = self.action_helper.get_action(db_labels)
            print(next_actions)
            if 'ignore' in next_actions:
                print('in')
                continue
            print('after')


            if applied_labels != cmk_labels:
                need_update = True

            if need_update:
                update_headers = {
                    'if-match': host_etag,
                }
                update_url = f"objects/host_config/{db_host.hostname}"
                update_body = {
                    'update_attributes': {
                        'ipaddress': '127.0.0.6',
                        'labels' : str({'os': 'osx'}),
                    }
                }


                #import pprint
                #pprint.pprint(cmk_host)
                #pprint.pprint(update_body)
                #pprint.pprint(headers)

                #pprint.pprint(cmk_host)

                update_response, _ = self.request(update_url, method="PUT",
                                                  data=update_body,
                                                  additional_header=update_headers)
                print(f"Update Host {update_response}")


@app.cli.command('export_to_cmk-v2')
@click.argument("account")
def get_cmk_data(account):
    """Add hosts to a CMK 2.x Insallation"""
    try:
        if target_config := get_account_by_name(account):
            job = UpdateCMKv2(target_config)
            job.run()
        else:
            print("Target not found")
    except CmkException as error_obj:
        print(f'CMK Connection Error: {error_obj}')
