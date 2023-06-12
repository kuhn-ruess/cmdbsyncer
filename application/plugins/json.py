"""
JSON Plugin
"""
#pylint: disable=too-many-arguments
import json
import click
from application import app
from application.models.host import Host
from application.modules.debug import ColorCodes
from application.helpers.get_account import get_account_by_name

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
            if host_obj.get_labels() != host:
                host_obj.set_import_sync()
                host_obj.set_labels(host)
            host_obj.set_import_seen()

            do_save = host_obj.set_account(account_dict=account)

            if do_save:
                host_obj.save()
