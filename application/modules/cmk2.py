"""
Central Request Modul to CMK 2.x
"""
import requests
from application import app, log

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
class CMK2():
    """
    Get Data from CMK
    """

    def __init__(self, config):
        """
        Inital
        """
        self.log = log
        self.config = config

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
        try:
            method = method.lower()
            if method == 'get':
                response = requests.get(url, headers=headers, params=data, verify=False)
            elif method == 'post':
                response = requests.post(url, json=data, headers=headers, verify=False)
            elif method == 'put':
                response = requests.put(url, json=data, headers=headers, verify=False)
            elif method == 'delete':
                response = requests.delete(url, headers=headers, verify=False)
                # Checkmk gives no json response here, so we directly return
                return True, response.headers

            error_whitelist = [
                #'Path already exists',
                'Not Found',
            ]

            if response.status_code != 200:
                if response.json()['title'] not in error_whitelist:
                    print(response.text)
                raise CmkException(response.json()['title'])
            return response.json(), response.headers
        except (ConnectionResetError, requests.exceptions.ProxyError):
            raise Exception("Cant connect to cmk site") # pylint: disable=raise-missing-from
