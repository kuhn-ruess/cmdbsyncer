#!/usr/bin/env python3
"""Import JDISC Data"""
#pylint: disable=logging-fstring-interpolation
import click

from syncerapi.v1 import (
    register_cronjob,
    cc,
    Host,
)

from syncerapi.v1.core import (
    cli,
    Plugin,
)
from syncerapi.v1.inventory import run_inventory


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

    def _inner_import(self):
        """
        Connect to Jdisc"
        """

        access_token = self._obtain_access_token()
        fields = [x.strip() for x in self.config['fields'].split(',')]
        if 'name' not in fields:
            fields.append('name')
        fields = "\n".join(fields)
        graphql_query = """{
        devices {
            findAll {"""+fields+"""
            }
          }
        }"""

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
        return response.json()['data']['devices']['findAll']


    def jdisc_import(self):
        """
        JDisc Import
        """
        for labels in self._inner_import():
            if 'name' not in labels:
                continue
            hostname = labels['name']
            if 'rewrite_hostname' in self.config and self.config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname,
                                                 self.config['rewrite_hostname'], labels)
            print(f" {cc.OKGREEN}* {cc.ENDC} Check {hostname}")
            del labels['name']
            host_obj = Host.get_host(hostname)
            host_obj.update_host(labels)
            do_save=host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
            else:
                print(f" {cc.WARNING} * {cc.ENDC} Managed by diffrent master")

    def jdisc_inventorize(self):
        """
        JDisc Inventorize
        """
        run_inventory(self.config, self._inner_import())

#   . CLI and Cron

@cli.group(name='jdisc')
def cli_jdisc():
    """JDisc commands"""

def jdisc_import(account):
    """
    Jdisc Inner Import
    """
    jdisc = JDisc(account)
    jdisc.name = f"Import data from {account}"
    jdisc.source = "jdisc_import"
    jdisc.jdisc_import()

@cli_jdisc.command('import_hosts')
@click.argument('account')
def cli_jdisc_import(account):
    """Import JDisc Hosts"""
    jdisc_import(account)


def jdisc_inventorize(account):
    """
    JDISC Inner Inventorize
    """
    jdisc = JDisc(account)
    jdisc.name = f"Inventorize data from {account}"
    jdisc.source = "jdisc_inventorize"
    jdisc.jdisc_inventorize()

@cli_jdisc.command('inventorize_hosts')
@click.argument('account')
def cli_jdisc_inventorize(account):
    """Inventorize JDISC Data"""
    jdisc_inventorize(account)

register_cronjob("JDisc: Import Hosts", jdisc_import)
register_cronjob("JDisc: Inventorize Data", jdisc_inventorize)
#.
