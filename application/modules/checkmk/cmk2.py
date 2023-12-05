"""
Central Request Modul to CMK 2.x
"""
#pylint: disable=logging-fstring-interpolation
from pprint import pformat
import requests
from application import app, log, logger
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
        if params.startswith('/'):
            params = params[1:]
        url = f'{address}/check_mk/api/1.0/{params}'
        headers = {
            'Authorization': f"Bearer {username} {password}"
        }
        response = False
        if additional_header:
            headers.update(additional_header)
        try:
            method = method.lower()
            #pylint: disable=missing-timeout
            logger.debug(f"Request ({method.upper()}) to {url}")
            logger.debug(f"Request Body: {data}")
            logger.debug(f"Request Headers: {headers}")
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
                return True, response.status_code


            #pylint: disable=line-too-long
            error_whitelist = [
                #'Path already exists',
                'Not Found',
                'The operation has failed.',
                'Mismatch between endpoint and internal data format. ',
                'Precondition required If-Match header required for this operation. See documentation.',
            ]

            if response.status_code != 200:
                # If the status Code is not 200,
                # we can't sure to get Json as response
                # so we try some failbacks and whitelist some cases
                try:
                    response_json = response.json()
                    logger.debug(f"Response Json: {pformat(response_json)}")
                except:
                    # pylint: disable=raise-missing-from
                    # Wired but on purpose:
                    # API 404 has JSON Response, every webserver 404 has not
                    if response.status_code == 404:
                        raise CmkException(f"Page not Found: {url}")
                    raise CmkException("Cant parse Checkmk Response")

                if response_json['title'] not in error_whitelist:
                    raise CmkException(f"{response_json['title']} {response_json.get('detail')}")
                return {}, {'status_code': response.status_code}
            resp_header = response.headers
            resp_header['status_code'] = response.status_code

            response_json = response.json()
            logger.debug(f"Response Json: {pformat(response_json)}")
            return response_json, resp_header
        except (ConnectionResetError, requests.exceptions.ProxyError):
            if response:
                return {}, {'status_code': response.status_code}
            return {}, {"error": "Checkmk Connections broken"}
