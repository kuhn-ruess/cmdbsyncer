"""
CSV Function
"""
#pylint: disable=too-many-arguments
import csv
import click
from application import app
from application.models.host import Host
from application.modules.plugin import Plugin
from application.modules.debug import ColorCodes
from application.helpers.get_account import get_account_by_name
from application.helpers.cron import register_cronjob

@app.cli.group(name='csv')
def _cli_csv():
    """CSV related commands"""


def compare_hosts(csv_path, delimiter, hostname_field, label_filter):
    """
    Compare lists from hosts which not in syncer
    """
    #pylint: disable=no-member, consider-using-generator
    if label_filter:
        host_list = []
        # we need to load the full plugins then
        plugin = Plugin()
        for host in Host.get_export_hosts():
            if label_filter in plugin.get_host_attributes(host, 'csv')['all']:
                host_list.append(host.hostname)
    else:
        host_list = list([x.hostname for x in Host.get_export_hosts()])
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field]
            if hostname not in host_list:
                print(hostname)

@_cli_csv.command('compare_hosts')
@click.argument("csv_path", default="")
@click.option("--delimiter", default=';')
@click.option("--hostname_field", default='host')
@click.option("--label_filter", default='')
def cli_compare_hosts(csv_path, delimiter, hostname_field, label_filter):
    """
    ## Check which Hosts from your CSV are not in the syncer

    ### Example
    _./cmdbsyncer csv compare_hosts path_to.csv --delimiter ';'_

    Args:
        csv_path (string): Path to CSV
        delimiter (string): --delimiter, Field delimiter.
        hostname_field (string): --hostname_field, Name of Colum where Hostname is found.
        label_filter (string): --label_filter, Filder for given Labelname
    """
    compare_hosts(csv_path, delimiter, hostname_field, label_filter)


def import_hosts(csv_path=None, delimiter=";", hostname_field="host", account=None):
    """
    Impor hosts from a CSV
    """
    #pylint: disable=no-member, consider-using-generator
    encoding = 'utf-8'
    if account:
        account = get_account_by_name(account)
        if 'hostname_field' in account:
            hostname_field = account['hostname_field']
        if 'delimiter' in account:
            delimiter = account['delimiter']
        if 'csv_path' in account:
            csv_path = account['csv_path']
        if 'path' in account:
            csv_path = account['path']
        if 'encoding' in account:
            encoding = account['encoding']

    if not csv_path:
        raise ValueError("No path given in account config")

    filename = csv_path.split('/')[-1]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"\
          f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")
    with open(csv_path, newline='', encoding=encoding) as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field].strip().lower()
            keys = list(row.keys())
            for dkey in keys:
                if not row[dkey]:
                    del row[dkey]
            if 'rewrite_hostname' in account and account['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname, account['rewrite_hostname'], row)
            print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
            host_obj = Host.get_host(hostname)
            del row[hostname_field]
            host_obj.update_host(row)
            if account:
                do_save = host_obj.set_account(account_dict=account)
            else:
                do_save = True
                host_obj.set_account(f"csv_{filename}", filename)

            if do_save:
                host_obj.save()

@_cli_csv.command('import_hosts')
@click.argument("csv_path", default="")
@click.option("--delimiter", default=';')
@click.option("--hostname_field", default='host')
@click.option("--account", default='')
def cli_import_hosts(csv_path, delimiter, hostname_field, account):
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
    import_hosts(csv_path, delimiter, hostname_field, account)

def inventorize_hosts(csv_path, delimiter, hostname_field, key, account):
    """
    Inventorize data from a CSV
    """
    #pylint: disable=no-member, consider-using-generator
    if account:
        account = get_account_by_name(account)
        if 'hostname_field' in account:
            hostname_field = account['hostname_field']
        if 'delimiter' in account:
            delimiter = account['delimiter']
        if 'csv_path' in account:
            csv_path = account['csv_path']
        if 'path' in account:
            csv_path = account['path']
        if 'inventorize_key' in account:
            key = account['inventorize_key']

    if not csv_path:
        raise ValueError("No path given in account config")

    filename = csv_path.split('/')[-1]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"\
          f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")
    new_attributes = {}
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field].strip().lower()
            keys = list(row.keys())
            for dkey in keys:
                if not row[dkey]:
                    del row[dkey]
            print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Got Data for {hostname}")
            del row[hostname_field]
            if 'rewrite_hostname' in account and account['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname, account['rewrite_hostname'], row)
            new_attributes[hostname] = row

    for host_obj in Host.get_export_hosts():
        print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {host_obj.hostname}")
        host_obj.update_inventory(key, new_attributes.get(host_obj.hostname, {}))
        host_obj.save()

@_cli_csv.command('inventorize_hosts')
@click.argument("csv_path", default="")
@click.option("--delimiter", default=';')
@click.option("--hostname_field", default='host')
@click.option("--key", default='csv')
@click.option("--account", default='')
def cli_inventorize_hosts(csv_path, delimiter, hostname_field, key, account):
    """
    ## Add Inventory Information to hosts
    Source is a CSV. Every other Column then the hostname Column, will translate
    into key:value attributes.

    ### Example
    _./cmdbsyncer csv inventorize_hosts path_to.csv --delimiter ';' --key "File1"_

    Args:
        csv_path (string): Path to CSV
        delimiter (string): --delimiter, Field delimiter
        hostname_field (string): --hostname_field, Name of Colum where Hostname is found
        key (string): --key, Group Name for Inventory data
    """
    inventorize_hosts(csv_path, delimiter, hostname_field, key, account)



register_cronjob('CSV: Import Hosts', import_hosts)
register_cronjob('CSV: Inventorize Hosts', inventorize_hosts)
