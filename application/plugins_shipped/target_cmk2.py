
"""
Add Hosts into CMK Version 2 Installations
"""
#pylint: disable=too-many-arguments
import click
import requests
from application import app, log
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.helpers.get_action import GetAction
from application.helpers.get_label import GetLabel
from application.helpers.get_hostparams import GetHostParams

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
        self.params_helper = GetHostParams('export')

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
            # Checkmk gives no json response here, so we directly return
            return True, response.headers

        error_whitelist = [
            'Path already exists',
            'Not Found',
        ]

        if response.status_code != 200:
            if response.json()['title'] not in error_whitelist:
                print(response.text)
            raise CmkException(response.json()['title'])
        return response.json(), response.headers

    def run(self): #pylint: disable=too-many-locals, too-many-branches
        """Run Actual Job"""
        # In Order to delete Hosts from Checkmk, we collect the ones we sync
        synced_hosts = []

        # Get all current folders in order that we later now,
        # which we need to create
        url = "domain-types/folder_config/collections/all"
        url += "?parent=/&recursive=true&show_hosts=false"
        api_folders = self.request(url, method="GET")
        existing_folders = []
        for folder in api_folders[0]['value']:
            existing_folders.append(folder['extensions']['path'])


        ## Start SYNC of Hosts into CMK
        for db_host in Host.objects():
            # Actions

            db_labels = db_host.get_labels()
            labels = self.label_helper.filter_labels(db_labels)

            host_params = self.params_helper.get_params(db_host.hostname)

            if host_params.get('ignore_hosts'):
                continue
            if host_params.get('custom_labels'):
                labels.update(host_params['custom_labels'])

            next_actions = self.action_helper.get_action(labels)
            if 'ignore' in next_actions:
                continue
            synced_hosts.append(db_host.hostname)
            labels['cmdb_syncer'] = self.account_id


            folder = False
            if 'move_folder' in next_actions:
                # Get the Folder where we move to
                folder = next_actions['move_folder'].lower()
                # Add leading / if missing
                if not folder.startswith('/'):
                    folder = "/" + folder
                # if we have a source folder, add him on front
                if 'source_folder' in next_actions:
                    folder = next_actions['source_folder'].lower() + folder
                    if not folder.startswith('/'):
                        folder = "/" + folder
                if folder not in existing_folders:
                    self.create_folder(folder)
                    existing_folders.append(folder)
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

        ## Cleanup, delete Hosts from this Source who are not longer in our DB or synced
        # Get all hosts with cmdb_syncer label and delete if not in synced_hosts
        url = "domain-types/host_config/collections/all"
        api_hosts = self.request(url, method="GET")
        for host in api_hosts[0]['value']:
            host_labels = host['extensions']['attributes'].get('labels',{})
            if host_labels.get('cmdb_syncer') == self.account_id:
                if host['id'] not in synced_hosts:
                    # Delete host
                    url = f"objects/host_config/{host['id']}"
                    self.request(url, method="DELETE")
                    print(f"Deleted host {host['id']}")


    def _create_folder(self, parent, subfolder):
        """ Helper to create tree of folders """
        url = "domain-types/folder_config/collections/all"
        body = {
            "name": subfolder,
            "title": subfolder.capitalize(),
            "parent": parent,
        }
        try:
            self.request(url, method="POST", data=body)
        except CmkException:
            # We ignore an existing folder
            pass


    def create_folder(self, folder):
        """ Create given folder if not yet exsisting """
        folder_parts = folder.split('/')[1:]
        if len(folder_parts) == 1:
            if folder_parts[0] == '':
                # we are in page root
                return
            parent = '/'
            subfolder = folder_parts[0]
            self._create_folder(parent, subfolder)
        else:
            next_parent = '/'
            for sub_folder in folder_parts:
                self._create_folder(next_parent, sub_folder)
                if next_parent == '/':
                    next_parent += sub_folder
                else:
                    next_parent  += '/' + sub_folder


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
            current_folder = cmk_host['extensions']['folder']
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
            db_host.set_target_update()


@app.cli.command('export_to_cmk-v2')
@click.argument("account")
def get_cmk_data(account):
    """Add hosts to a CMK 2.x Insallation"""
    try:
        target_config = get_account_by_name(account)
        if target_config:
            job = UpdateCMKv2(target_config)
            job.run()
        else:
            print("Target not found")
    except CmkException as error_obj:
        print(f'CMK Connection Error: {error_obj}')
