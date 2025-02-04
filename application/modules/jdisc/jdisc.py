#!/usr/bin/env python3
"""Import JDISC Data"""
#pylint: disable=logging-fstring-interpolation

from syncerapi.v1 import (
    cc,
    Host,
)

from syncerapi.v1.core import (
    Plugin,
)

class JDisc(Plugin):
    """
    JDisc Plugin
    """

    def _obtain_access_token(self) -> str:
        """Obtains a Access token

        Returns:
            str: The Access Token
        """
        username = self.config['username']
        password = self.config['password']
        graphql_query = '''
        mutation login {
            authentication {
                login(login: "'''+username+'''", password: "'''+password+'''", ) {
                    accessToken
                    refreshToken
                    status
                }
            }
        }
        '''
        data = {'query': graphql_query,
                'operationName': "login", "variables": None}

        response = self.inner_request(
            'POST',
            url=self.config['address'],
            data=data,
              headers={
                  'Content-Type': 'application/json',
                  'Accept': 'application/json',
              },
        )
        return response.json()['data']['authentication']['login']['accessToken']

    def handle_object(self, objects, obj_type):
        """
        Handle host actions """
        for found_obj in objects:
            try:
                found_obj = found_obj[obj_type]
                if not 'name' in found_obj:
                    continue
                name = found_obj['name']
                del found_obj['name']
                host_obj = Host.get_host(name)
                do_save = host_obj.set_account(account_dict=self.config)
                if do_save:
                    host_obj.is_object = True
                    host_obj.object_type = obj_type
                    host_obj.update_host(found_obj)
                    host_obj.save()
                print(f" {cc.OKGREEN}* {cc.ENDC} Created object {name}")
            except Exception as error:
                if self.debug:
                    raise
                self.log_details.append((f'export_error {name}', str(error)))
                print(f" Error in process: {error}")

    #def get_custom_fields_query(self, mode):
    #    """
    #    Build User Defined Payload
    #    """
    #    fields = [x.strip() for x in self.config['fields'].split(',')]
    #    if 'name' not in fields:
    #        fields.append('name')
    #    fields = "\n".join(fields)
    #    return """{
    #    """+mode+""" {
    #        findAll {"""+fields+"""
    #        }
    #      }
    #    }"""

    def run_query(self):
        """
        Connect to Jdisc"
        """
        access_token = self._obtain_access_token()

        graphql_query = self.get_query()

        data = {'query': graphql_query}
        auth_header = f'Bearer {access_token}'

        response = self.inner_request(
                "POST",
                url=self.config['address'],
                headers={'Authorization': auth_header,
                           'Content-Type': 'application/json',
                           'Accept': 'application/json',
                  },
                  data=data,
        )
        rsp_json = response.json()
        if not rsp_json['data']:
            raise ValueError(rsp_json)

        return rsp_json['data']
