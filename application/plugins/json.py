"""
JSON Plugin
"""
#pylint: disable=too-many-arguments, logging-fstring-interpolation
import json
import click

import requests
from requests.auth import HTTPBasicAuth

from application import app, logger
from application.models.host import Host
from application.modules.debug import ColorCodes
from application.helpers.get_account import get_account_by_name
from application.helpers.cron import register_cronjob

@app.cli.group(name='json')
def _cli_json():
    """JSON related Commands"""

@_cli_json.command('import_hosts')
@click.argument("json_path", default=False)
@click.option("--hostname_field", default='host')
@click.option("--account")
def import_hosts(json_path, hostname_field, account):
    """
    ## Import Hosts from JSON File
    """
    #pylint: disable=no-member, consider-using-generator


    account = get_account_by_name(account)
    if 'hostname_field' in account:
        hostname_field = account['hostname_field']

    if 'path' in account:
        json_path = account['path']

    if not json_path:
        raise ValueError("No path given in account config")

    filename = json_path.split('/')[-1]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"\
          f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")

    with open(json_path, newline='', encoding='utf-8') as json_file:
        data = json.load(json_file)
        for host in data:
            hostname = host[hostname_field]
            print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
            del host[hostname_field]
            host_obj = Host.get_host(hostname)
            host_obj.update_host(host)

            do_save = host_obj.set_account(account_dict=account)

            if do_save:
                host_obj.save()

@app.cli.group(name='rest')
def _cli_rest():
    """REST API related Commands"""


def import_hosts_json(account):
    """
    Import Hosts from REST API
    """
    account = get_account_by_name(account)
    headers = {}
    auth = None
    if account.get('request_headers'):
        headers = dict(account['request_headers'])

    if account.get('use_auth_basic'):
        auth = HTTPBasicAuth(account['username'], account['password'])

    logger.debug(f"Auth: {auth}")

    response = requests.post(account['address'], headers=headers, auth=auth, timeout=30)
    data = response.json()
    logger.debug(f"Response: {data}")

    for entry in data[account['data_key']]:
        hostname = entry[account['hostname_field']]
        del entry[account['hostname_field']]

        host_obj = Host.get_host(hostname)
        host_obj.update_host(entry)

        do_save = host_obj.set_account(account_dict=account)

        if do_save:
            host_obj.save()

@_cli_rest.command('import_hosts')
@click.argument("account")
def cli_import_hosts_json(account):
    """
    Import Json direct from Rest API
    """
    return import_hosts_json(account)

register_cronjob('REST API: Import Hosts', import_hosts_json)
