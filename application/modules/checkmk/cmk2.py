"""
Central Request Modul to CMK 2.x
"""
import requests
from application import app, log
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

    def __init__(self):
        """
        Inital
        """
        self.log = log
        self.verify = not app.config.get('DISABLE_SSL_ERRORS')
        self.config = {}

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
            #pylint: disable=missing-timeout
            if method == 'get':
                response = requests.get(url,
                                        headers=headers,
                                        params=data,
                                        verify=self.verify,
                                       )
            elif method == 'post':
                response = requests.post(url, json=data, headers=headers, verify=self.verify)
            elif method == 'put':
                response = requests.put(url, json=data, headers=headers, verify=self.verify)
            elif method == 'delete':
                response = requests.delete(url, headers=headers, verify=self.verify)
                # Checkmk gives no json response here, so we directly return
                return True, response.headers

            #pylint: disable=line-too-long
            error_whitelist = [
                #'Path already exists',
                'Not Found',
                'The operation has failed.',
                'Mismatch between endpoint and internal data format. ',
                'Precondition required If-Match header required for this operation. See documentation.',
            ]

            if response.status_code != 200:
                response_json = response.json()
                if response_json['title'] not in error_whitelist:
                    raise CmkException(f"{response_json['title']} {response_json['detail']}")
                return {}, {}
            return response.json(), response.headers
        except (ConnectionResetError, requests.exceptions.ProxyError):
            print(response.text)
            return {}, {}
