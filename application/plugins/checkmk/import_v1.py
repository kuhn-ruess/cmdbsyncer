#!/usr/bin/env python3
"""
Get Hosts from a CMKv1 Instance
"""
import ast
import click
import requests
from mongoengine.errors import DoesNotExist
from application import log
from application.models.host import Host, HostError
from application.helpers.get_account import get_account_by_name


class ImportCheckmk1():
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

        response = requests.post(url, {"request": formated}, verify=False, timeout=180)
        return ast.literal_eval(response.text)


    def run(self):
        """Run Actual Job"""
        all_hosts = self.request("get_all_hosts", {})['result']
        found_hosts = []
        for hostname, _host_data in all_hosts.items():
            found_hosts.append(hostname)
            try:
                host = Host.objects.get(hostname=hostname)
                host.add_log('Found in Source')
            except DoesNotExist:
                host = Host()
                host.hostname = hostname
                host.add_log("Inital Add")
                host.set_source_update()
            except HostError as error_obj:
                host.add_log(f"Update Error {error_obj}")

            do_save = host.set_account(account_dict=self.config)
            if do_save:
                host.save()

