"""
Central Request Modul to CMK 2.x
"""
#pylint: disable=logging-fstring-interpolation
import requests
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


    def __init__(self, account=False):
        """
        Check for Version
        """
        super().__init__(account)

        if account and not self.checkmk_version:
            data = self.request('/version')[0]
            self.checkmk_version = data['versions']['checkmk']


    def request(self, url, method='GET', data=None, params=None, additional_header=None):
        """
        Handle Request to CMK
        """
        address = self.config['address']
        username = self.config['username']
        password = self.config['password']
        if url.startswith('/'):
            url = url[1:]

        url = f'{address}/check_mk/api/1.0/{url}'
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
