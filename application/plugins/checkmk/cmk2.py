"""
Central Request Modul to CMK 2.x
"""
#pylint: disable=logging-fstring-interpolation
import multiprocessing
import requests
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
#from requests.exceptions import ConnectionError
from application import app
from application.modules.plugin import Plugin

@app.cli.group(name='checkmk')
def cli_cmk():
    """Checkmk commands"""

if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)

class CmkException(Exception):
    """Cmk Errors"""

#pylint: disable=too-few-public-methods
class CMK2(Plugin):
    """
    Get Data from CMK
    """

    checkmk_version = False

    checkmk_hosts = {}

    existing_folders = []
    existing_folders_attributes = {}
    custom_folder_attributes = {}


    def __init__(self, account=False):
        """
        Check for Version
        """
        super().__init__(account)

        if self.config and not self.checkmk_version:
            data = self.request('/version')[0]
            self.checkmk_version = data['versions']['checkmk']


    def request(self, url, method='GET', data=None, params=None, additional_header=None, api_version="api/1.0/"):
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
            #pylint: disable=missing-timeout
            response = self.inner_request(method, url, json=data, headers=headers, params=params)

            try:
                response_json = response.json()
            except requests.exceptions.JSONDecodeError:
                response_json = {}

            resp_header = response.headers

            #pylint: disable=line-too-long
            error_whitelist = [
                #'Path already exists',
                'Not Found',
                'The operation has failed.',
                'Mismatch between endpoint and internal data format. ',
                'Precondition required If-Match header required for this operation. See documentation.',
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
        except ConnectionError:
            #pylint: disable=raise-missing-from
            raise CmkException("Can't connect to Checkmk")

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
                self.checkmk_hosts[host['id']] = host
                progress.update(task1, advance=1)


    def get_hosts_of_folder(self, folder, return_dict, extra_params):
        """ Get Hosts of given folder """
        folder = folder.replace('/','~')
        url = f"objects/folder_config/{folder}/collections/hosts{extra_params}"
        api_hosts = self.request(url, method="GET")
        for host in api_hosts[0]['value']:
            return_dict[host['id']] = host

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
            manager = multiprocessing.Manager()
            return_dict = manager.dict()
            with multiprocessing.Pool() as pool:
                for folder in self.existing_folders:
                    pool.apply_async(self.get_hosts_of_folder,
                                     args=(folder, return_dict, extra_params,),
                                     callback=lambda x: progress.advance(task1))

                pool.close()
                pool.join()
                self.checkmk_hosts.update(return_dict)
