
"""
Add Hosts into CMK Version 2 Installations
"""
import click
import requests
from application import app, log
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.helpers.get_action import GetAction
from application.helpers.get_label import GetLabel

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
        self.label_helper = GetLabel()

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
            response = requests.post(url, json=data, headers=headers, verify=False)
        elif method == 'put':
            response = requests.put(url, json=data, headers=headers, verify=False)
        elif method == 'delete':
            response = requests.delete(url, headers=headers, verify=False)

        if response.status_code != 200:
            print(response.text)
            raise CmkException(response.json()['title'])
        return response.json(), response.headers

    def run(self): #pylint: disable=too-many-locals
        """Run Actual Job"""
        for db_host in Host.objects():
            # Actions

            db_labels = db_host.get_labels()
            labels = self.label_helper.filter_labels(db_labels)

            next_actions = self.action_helper.get_action(labels)
            if 'ignore' in next_actions:
                continue

            folder = False
            if 'move_folder' in next_actions:
                folder = next_actions['move_folder']
            # Check if Host Exists
            url = f"objects/host_config/{db_host.hostname}"
            try:
                cmk_host, headers = self.request(url, "GET")
            except CmkException as error:
                if str(error) == "Not Found":
                    self.create_host(db_host, folder, labels)
            else:
                host_etag = headers['ETag']
                self.update_host(db_host, cmk_host, host_etag, folder, labels)

    def create_host(self, db_host, folder, labels):
        """
        Create the not yet existing host in CMK
        """
        url = "/domain-types/host_config/collections/all"
        body = {
            'host_name' : db_host.hostname,
            'folder' : '/' if not folder else folder,
            'attributes': {
                'labels' : labels,
            }
        }

        self.request(url, method="POST", data=body)
        print(f"Created Host {db_host.hostname}")

    def update_host(self, db_host, cmk_host, host_etag, folder, labels):
        """
        Update a Existing Host in Checkmk
        """
        need_update = False

        update_headers = {
            'if-match': host_etag,
        }

        # compare Labels
        cmk_labels = cmk_host['extensions']['attributes'].get('labels', {})

        if labels != cmk_labels:
            need_update = True


        if folder:
            # Check if we really need to move
            for link in cmk_host['links']:
                if link['rel'] == 'urn:com.checkmk:rels/folder_config':
                    current_folder = link['href'].split('~')[-1]
                    if current_folder != folder[1:]:
                        update_url = f"/objects/host_config/{db_host.hostname}/actions/move/invoke"
                        update_body = {
                            'target_folder': folder
                        }
                        _, header = self.request(update_url, method="POST",
                                     data=update_body,
                                     additional_header=update_headers)
                        # Need to update the header after last request
                        update_headers = {
                            'if-match': header['ETag'],
                        }

        if db_host.need_update():
            # Triggert after Time,
            # Or if force_update is checked in
            # the Admin Panel
            need_update = True

        if need_update:
            update_url = f"objects/host_config/{db_host.hostname}"
            update_body = {
                'update_attributes': {
                    'labels' : labels,
                }
            }

            self.request(update_url, method="PUT",
                         data=update_body,
                         additional_header=update_headers)
            print(f"Update Host {db_host.hostname}")


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
