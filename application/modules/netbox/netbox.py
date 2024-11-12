import requests
from application.modules.plugin import Plugin

from syncerapi.v1 import (
    cc,
)

class SyncNetbox(Plugin):
    """
    Netbox Base Class
    """

#   .-- Get Host Data
    def get_host_data(self, db_host, attributes):
        """
        Return commands for fullfilling of the netbox params
        """
        return self.actions.get_outcomes(db_host, attributes)
#.
#   .-- Object Need Update?
    def need_update(self, device_payload, target_payload, ignore_fields=None):
        """
        Compare Request Payload with Device Response
        """
        keys = []
        #print('##################')
        #print(target_payload)
        #print(device_payload)
        #print('##################')
        for key, value in target_payload.items():
            if ignore_fields and key in ignore_fields:
                continue
            current_value = device_payload.get(key, False)
            if current_value is False:
                continue
            if isinstance(current_value, dict):
                sub_value = current_value.get('id')
                if not sub_value:
                    sub_value = current_value.get('value')
                current_value = sub_value
            #print(f'{key}: {current_value} -> {value}')
            if value != current_value:
                keys.append(key)
        return keys
#.

    def get_objects(self, url, syncer_only=False):
        """
        Read full list of given Objects
        """
        print(f"{cc.OKGREEN} -- {cc.ENDC}Netbox: "\
              f"Read all Objects (Filter only CMDB Syncer: {syncer_only})")
        if syncer_only:
            url += f"?cf_cmdbsyncer_id={self.config['_id']}"
        ips = self.request(url, "GET")
        return {x['display']:x for x in ips}

    def update_object(self, url, payload):
        """
        Send Update Request to Netbox
        """
        self.request(url, 'PATCH', payload)
        self.console(f' - Updated Object')

    def create_object(self, url, payload):
        """
        Send Create Request to Netbox
        """
        self.request(url, "POST", payload)
        self.console(' - Created Object')

    @staticmethod
    def extract_data(data):
        """
        Extract Netbox fields
        """
        labels = {}
        for key, value in data.items():
            if key == 'custom_fields':
                if 'cmdbsyncer_id' in value:
                    del value['cmdbsyncer_id']
                labels.update(value)
            elif isinstance(value, str):
                labels[key] = value
            elif isinstance(value, dict):
                if 'display' in value:
                    labels[key] = value['display']
                elif 'label' in value:
                    labels[key] = value['label']
        return labels

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
        response_json = ""
        if additional_header:
            headers.update(additional_header)
        try:
            method = method.lower()
            #pylint: disable=missing-timeout

            response = self.inner_request(method, url, data, headers)

            if response.status_code == 403:
                raise Exception("Invalid Login, you may need to create a login token")
            if response.status_code >= 299:
                self.log_details.append(('error', f'Exception: {response.text}'))
                print(f"Error in response {response.text}")
                return {}
            try:
                response_json = response.json()
            except:
                pass
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
                        sub_response= self.inner_request("GET", next_page, headers=headers).json()
                        next_page = sub_response['next']
                        results += sub_response['results']
                return results
            return response_json
        except (ConnectionResetError, requests.exceptions.ProxyError):
            return {}
