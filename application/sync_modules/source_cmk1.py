#!/usr/bin/env python3
"""
Update Hosts in Monitoring Based on Local DB
"""
import ast
import click
import requests
from mongoengine.errors import DoesNotExist
from application import app, log
from application.models.host import Host
from application.helpers.get_source import get_source_by_name


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

    def request(self, what, payload):
        """
        Generic function to contact the api
        """
        config = self.config
        config["action"] = what

        url = "{address}/check_mk/webapi.py" \
              "?action={action}&_username={username}" \
              "&_secret={password}&output_format=python&request_format=python".format(**config)

        if payload: # payload is not empty
            formated = ascii(payload).replace(" '", " u'")
            formated = formated.replace("{'", "{u'")
        else: # payload is empty
            formated = ascii(payload)

        response = requests.post(url, {"request": formated}, verify=False)
        return ast.literal_eval(response.text)


    def run(self):
        """Run Actual Job"""
        all_hosts = self.request("get_all_hosts", {})['result']
        for hostname, _host_data in all_hosts.items():
            try:
                host = Host.objects.get(hostname=hostname)
                self.log.debug("Alrady in DB: {}".format(hostname))
            except DoesNotExist:
                self.log.debug("Create in DB: {}".format(hostname))
                host = Host()
                host.hostname = hostname
            host.save()


@app.cli.command('import_cmk-v1')
@click.argument("source")
def get_cmk_data(source):
    """Get All hosts from CMK and add them to db"""
    if source_config := get_source_by_name(source):
        getter = DataGeter(source_config)
        getter.run()
    else:
        print("Source not found")
