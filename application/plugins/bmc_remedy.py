"""
BMC Remedy Plugin
"""
import requests
import click

from application import app

from syncerapi.v1 import (
    get_account,
    register_cronjob,
    cc,
)

@app.cli.group(name='bmc-remedy')
def _cli_bmc_remedy():
    """BMC Remedy Import"""

class RemedySyncer():
    """
    BMC Remedy
    """

    def __init__(self, config):
        """
        Init
        """
        self.account_dict = config
        self.account_id = str(config['_id'])
        self.address = config['address']
        self.user = config['username']
        self.password = config['password']
        self.verify = not app.config.get('DISABLE_SSL_ERRORS')
        self.config = config

#   .-- get_auth_token
    def get_auth_token(self):
        """
        Return Auth Token
        """
        print(f"{cc.OKGREEN} -- {cc.ENDC}Get Auth Token")
        url = f"{self.address}/api/jwt/login"
        auth_data = {
            'username': self.user,
            'password': self.password,
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        response = requests.post(
              url,
              data=auth_data,
              headers=headers,
              verify=self.verify,
              timeout=30,
        )

        if response.status_code == 200:
            return response.text
        #pylint: disable=broad-exception-raised
        raise Exception(f"Connection Problem {response.status_code}: {response.text}")
#.
#    .-- Get Hosts
    def get_hosts(self):
        """
        Get Hosts from Remedy
        """

        auth_token = self.get_auth_token()
        url = f"{self.address}/api/cmdb/v1.0/classqueries/"\
              f"{self.config['namespace']}/{self.config['class_name']}"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'AR-JWT {auth_token}'
        }

        response = requests.get(
              url,
              headers=headers,
              verify=self.verify,
              timeout=30,
        )

        print(response.text)
        print("Not yet implemented")
#.

def get_hosts(account):
    """
    Get Remedy Hosts
    """
    try:
        if target_config := get_account(account):
            job = RemedySyncer(target_config)
            job.get_hosts()
        else:
            print(f"{cc.FAIL} Target not found {cc.ENDC}")
    except Exception as error_obj: #pylint: disable=broad-except
        print(f'C{cc.FAIL}Error: {error_obj} {cc.ENDC}')


@_cli_bmc_remedy.command('get_hosts')
@click.argument('account')
def cli_get_hosts(account):
    """Sync Hosts from Remedy"""
    get_hosts(account)


register_cronjob("BMC Remedy: Get Hosts", get_hosts)
