#!/usr/bin/env python3
"""
Get Hosts from a CMKv2 Instance
"""
import click
import requests
from mongoengine.errors import DoesNotExist
from application import app, log
from application.plugins_shipped.target_cmk2 import cli_cmk
from application.models.host import Host, HostError
from application.helpers.get_account import get_account_by_name


if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)

class CmkException(Exception):
    """Cmk Errors"""


class DataGeter():
    """
    Get Data from CMK
    """

    def __init__(self, config):
        """
        Inital
        """
        self.log = log
        self.config = config
        self.account_id = str(config['_id'])
        self.account_name = config['name']

    def request(self, url=False):
        """
        Handle Request to CMK
        """
        address = self.config['address']
        username = self.config['username']
        password = self.config['password']
        if not url:
            url = f'{address}/check_mk/api/1.0/domain-types/host_config/collections/all'
        headers = {
            'Authorization': f"Bearer {username} {password}"
        }
        response = requests.get(url, headers=headers, verify=False)
        if response.status_code != 200:
            raise CmkException(response.json()['title'])
        return response.json()

    def run(self):
        """Run Actual Job"""
        found_hosts = []
        for hostdata in self.request()['value']:
            hostname = hostdata['title']
            host_details = self.request(hostdata['href'])

            found_hosts.append(hostname)
            try:
                host = Host.objects.get(hostname=hostname)
                host.add_log('Found in Source')
            except DoesNotExist:
                host = Host()
                host.hostname = hostname
                host.add_log("Inital Add")

            try:
                host.set_account(self.account_id, self.account_name)
                attributes = host_details['extensions']['attributes']
                if 'labels' in attributes:
                    host.add_labels(attributes['labels'])
                host.set_source_update()
            except HostError as error_obj:
                host.add_log(f"Update Error {error_obj}")
            host.save()

        for host in Host.objects(source_account_id=self.account_id, available=True):
            if host.hostname not in found_hosts:
                host.set_source_not_found()
                host.save()


@cli_cmk.command('import_v2')
@click.argument("account")
def get_cmk_data(account):
    """Get All hosts from a CMK 2.x Installation and add them to local db"""
    try:
        source_config = get_account_by_name(account)
        if source_config:
            getter = DataGeter(source_config)
            getter.run()
        else:
            print("Source not found")
    except CmkException as error_obj:
        print(f'CMK Connection Error: {error_obj}')
