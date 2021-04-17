#!/usr/bin/env python3
"""
Get Hosts from a CMKv2 Instance
"""
import click
import requests
from mongoengine.errors import DoesNotExist
from application import app, log
from application.models.host import Host, HostError
from application.helpers.get_source import get_source_by_name

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
        self.source_id = str(config['_id'])
        self.source_name = config['name']

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
                host.set_hostname(hostname)
                host.add_log("Inital Add")

            try:
                host.set_source(self.source_id, self.source_name)
                attributes = host_details['extensions']['attributes']
                if 'labels' in attributes:
                    host.add_labels(attributes['labels'])
                host.set_source_update()
            except HostError as error_obj:
                host.add_log(f"Update Error {error_obj}")
            host.save()

        for host in Host.objects(source_id=self.source_id, available_on_source=True):
            if host.hostname not in found_hosts:
                host.set_source_not_found()
                host.save()


@app.cli.command('import_cmk-v1')
@click.argument("source")
def get_cmk_data(source):
    """Get All hosts from CMK and add them to db"""
    try:
        if source_config := get_source_by_name(source):
            getter = DataGeter(source_config)
            getter.run()
        else:
            print("Source not found")
    except CmkException as error_obj:
        print(f'CMK Connection Error: {error_obj}')
