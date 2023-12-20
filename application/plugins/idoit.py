"""
idoit Function
"""
#pylint: disable=too-many-arguments
import click
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from application import app
from application.models.host import Host
from application.modules.plugin import Plugin
from application.modules.debug import ColorCodes
from application.helpers.get_account import get_account_by_name
from application.helpers.cron import register_cronjob

from pprint import pprint

@app.cli.group(name='idoit')
def _cli_idoit():
    """idoit related commands"""


def import_hosts(account):
    """
    Impor hosts from idoit
    """
    #pylint: disable=no-member, consider-using-generator
    config = get_account_by_name(account)
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"\
          f"{ColorCodes.UNDERLINE}{config['name']}{ColorCodes.ENDC}")

    url = f"{config['address']}/src/jsonrpc.php"

    auth = HTTPBasicAuth(config['username'], config['password'])
    json_data ={
    "version": "2.0",
    "method": "cmdb.objects.read",
    "params": {
        "filter": {
            "type": "C__OBJTYPE__SERVER",
            "status": "C__RECORD_STATUS__NORMAL"
        },
        "apikey": config["api_token"],
        "language": "de"
    },
    "id": 1
    }
    response = requests.post(url, auth=auth, json=json_data)

    for row in response.json()["result"]:
        hostname = row["title"]
        del(row["title"])
        print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
        host_obj = Host.get_host(hostname)
        host_obj.update_host(row)
        do_save = host_obj.set_account(account_dict=config)

        if do_save:
            host_obj.save()

@_cli_idoit.command('import_hosts')
@click.option("--account")
def cli_import_hosts(account):
    """
    ## Import Hosts from CSV and make File the Master
    Every CSV column, other then the host column, will translate
    into key:value attributes.

    If you seet account as parameter, all config will be read from there

    ### Example
    _./cmdbsyncer csv import_hosts path_to.csv --delimiter ';'_


    Args:
        csv_path (string): Path to CSV
        delimiter (string): --delimiter, Field delimiter
        hostname_field (string): --hostname_field, Name of Colum where Hostname is found
        account (string): --account, Name of Account to read config from
    """
    import_hosts(account)

register_cronjob('idoit: Import Hosts', import_hosts)
