import requests
from application.modules.plugin import Plugin

from syncerapi.v1 import (
    cc,
)

class SyncNetbox(Plugin):
    """
    Netbox Base Class
    """
    def request(self, path, method='GET', data=None, additional_header=None):
        """
        Handle Request to Netbox
        """
        address = self.config['address']
        password = self.config['password']
        url = f'{address}/api/{path}'
        headers = {
            'Authorization': f"Token {password}",
            'Content-Type': 'application/json',
        }
        if additional_header:
            headers.update(additional_header)
        try:
            method = method.lower()
            #pylint: disable=missing-timeout

            response = self.inner_request(method, url, data, headers)

            if response.status_code == 403:
                raise Exception("Invalid Login, you may need to create a login token")
            if response.status_code >= 299:
                print("Error in response, enable debug_log to see more")
            try:
                response_json = response.json()
            except:
                raise
            if 'results' in response_json:
                results = []
                results += response_json['results']
                if response_json['next']:
                    total = response_json['count']
                    request_count = int(round(total/len(response_json['results']),0)) + 1
                    print(f" -- Require {request_count} requests. {total} objects in total")
                    counter = 0
                    next_page = response_json['next']
                    while next_page:
                        counter += 1
                        process = 100.0 * counter / request_count
                        # pylint: disable=line-too-long
                        print(f"   {cc.OKGREEN}({process:.0f}%)...{counter}/{request_count}{cc.ENDC}")
                        sub_response= requests.get(next_page, headers=headers, verify=self.verify).json()
                        next_page = sub_response['next']
                        results += sub_response['results']
                return results
            return response_json
        except (ConnectionResetError, requests.exceptions.ProxyError):
            return {}
