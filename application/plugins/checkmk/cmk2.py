"""
Central Request Modul to CMK 2.x
"""
import multiprocessing
import requests
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
#from requests.exceptions import ConnectionError
from application import app
from application.modules.plugin import Plugin
from application.helpers.plugins import register_cli_group

cli_cmk = register_cli_group(app, 'checkmk', 'checkmk', "Checkmk commands")

if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)

class CmkException(Exception):
    """Cmk Errors"""

class CMK2(Plugin):
    """
    Get Data from CMK
    """

    checkmk_version = False

    checkmk_hosts = {}

    existing_folders = []
    existing_folders_attributes = {}
    custom_folder_attributes = {}

    @staticmethod
    def _compact_host_data(host):
        """
        Keep only the host fields the syncer actually reads later.

        The CheckMK API returns large host documents. Retaining only the
        required fields reduces memory usage noticeably during big sync runs.
        """
        extensions = host.get('extensions', {})
        return {
            'extensions': {
                'attributes': extensions.get('attributes', {}),
                'folder': extensions.get('folder', '/'),
                'is_cluster': extensions.get('is_cluster', False),
                'cluster_nodes': extensions.get('cluster_nodes', []),
            }
        }


    def __init__(self, account=False):
        """
        Check for Version
        """
        super().__init__(account)

        if self.config and not self.checkmk_version:
            data = self.request('/version')[0]
            self.checkmk_version = data['versions']['checkmk']


    def request(self, url, method='GET', data=None,  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
                params=None, additional_header=None, api_version="api/1.0/"):
        """
        Handle Request to CMK
        """
        address = self.config['address']
        username = self.config['username']
        password = self.config['password']
        if url.startswith('/'):
            url = url[1:]

        url = f'{address}/check_mk/{api_version}{url}'
        headers = {
            'Authorization': f'Bearer {username} {password}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        response = False
        if additional_header:
            headers.update(additional_header)

        if method.lower() in ['post', 'put', 'delete']:
            headers['Content-Type'] = 'application/json'


        try:
            response = self.inner_request(method, url, json=data, headers=headers, params=params)

            try:
                response_json = response.json()
            except requests.exceptions.JSONDecodeError:
                response_json = {}

            resp_header = response.headers

            error_whitelist = [
                #'Path already exists',
                'Not Found',
                'The operation has failed.',
                'Mismatch between endpoint and internal data format. ',
                'Precondition required If-Match header required '
                'for this operation. See documentation.',
            ]
            if response.status_code == 204: # No Content
                return {}, {'status_code': response.status_code}
            if response.status_code == 404:
                return {}, {"error": "Object not found"}
            if response.status_code != 200:
                if  response_json.get('title') not in error_whitelist:
                    raise CmkException(f"{response_json.get('title')} "\
                                       f"{response_json.get('detail')}"\
                                       f"{response_json.get('fields')}")
                return {}, {'status_code': response.status_code}
            resp_header['status_code'] = response.status_code

            return response_json, resp_header
        except (ConnectionResetError, requests.exceptions.ProxyError):
            if response:
                return {}, {'status_code': response.status_code}
            return {}, {"error": "Checkmk Connections broken"}
        except ConnectionError as exc:
            raise CmkException("Can't connect to Checkmk") from exc

    def fetch_checkmk_folders(self):
        """
        Fetch list of Folders in Checkmk
        """
        url = "domain-types/folder_config/collections/all"
        url += "?parent=/&recursive=true&show_hosts=false"
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Fetching Current Folders", start=False)
            api_folders = self.request(url, method="GET")
            if not api_folders[0]:
                raise CmkException("Cant connect or auth with CMK")
            progress.update(task1, total=len(api_folders[0]['value']), start=True)
            for folder in api_folders[0]['value']:
                progress.update(task1, advance=1)
                path = folder['extensions']['path']
                attributes = folder['extensions']['attributes']
                self.existing_folders_attributes[path] = attributes
                self.existing_folders_attributes[path].update({'title': folder['title']})
                self.existing_folders.append(path)

    def fetch_all_checkmk_hosts(self, extra_params=""):
        """
        Classic full Fetch
        """
        url = f"domain-types/host_config/collections/all{extra_params}"
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Fetching Hosts", start=False)
            progress.console.print("Waiting for Checkmk Response")
            api_hosts = self.request(url, method="GET")
            progress.update(task1, total=len(api_hosts[0]['value']), start=True)
            for host in api_hosts[0]['value']:
                self.checkmk_hosts[host['id']] = self._compact_host_data(host)
                progress.update(task1, advance=1)


    def get_hosts_of_folder(self, folder, extra_params):
        """Get hosts of the given folder as a plain dict."""
        folder_url = folder.replace('/','~')
        url = f"objects/folder_config/{folder_url}/collections/hosts{extra_params}"
        api_hosts = self.request(url, method="GET")
        return_dict = {}
        for host in api_hosts[0]['value']:
            return_dict[host['id']] = self._compact_host_data(host)
        return return_dict

    def _fetch_checkmk_host_by_folder(self, extra_params=""):
        """
        Check the folder Structure and get hosts
        whit multiple request
        """
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            num_folders = len(self.existing_folders)

            task1 = progress.add_task("Fetching Hosts folder by folder", total=num_folders)
            with multiprocessing.Pool() as pool:
                tasks = []
                for folder in self.existing_folders:
                    task = pool.apply_async(self.get_hosts_of_folder, args=(folder, extra_params,))
                    tasks.append(task)

                for task in tasks:
                    self.checkmk_hosts.update(task.get())
                    progress.advance(task1)
                pool.close()
                pool.join()
