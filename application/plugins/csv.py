
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

@app.cli.group(name='csv')
def _cli_csv():
    """CSV related commands"""


@_cli_csv.command('compare_hosts')
@click.argument("csv_path")
@click.option("--delimiter", default=';')
@click.option("--hostname_field", default='host')
@click.option("--label_filter", default='')
def compare_hosts(csv_path, delimiter, hostname_field, label_filter):
    """
    Check which Hosts from your CSV are not in the syncer

    Example
    =======
    _./cmdbsyncer csv compare_hosts path_to.csv --delimiter ';'_

    Args:
        csv_path (string): Path to CSV
        delimiter (string): --delimiter, Field delimiter.
        hostname_field (string): --hostname_field, Name of Colum where Hostname is found.
        label_filter (string): --label_filter, Filder for given Labelname
    """
    #pylint: disable=no-member, consider-using-generator
    if label_filter:
        host_list = []
        # we need to load the full plugins then
        plugin = Plugin()
        for host in Host.objects(available=True):
            if label_filter in plugin.get_host_attributes(host)['all']:
                host_list.append(host.hostname)
    else:
        host_list = list([x.hostname for x in Host.objects(available=True)])
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field]
            if hostname not in host_list:
                print(hostname)

@_cli_csv.command('import_hosts')
@click.argument("csv_path")
@click.option("--delimiter", default=';')
@click.option("--hostname_field", default='host')
def import_hosts(csv_path, delimiter, hostname_field):
    """
    Import Hosts from CSV and make File the Master
    Every CSV column, other then the host column, will translate
    into key:value attributes.

    Example
    =======
    _./cmdbsyncer csv import_hosts path_to.csv --delimiter ';'_


    Args:
        csv_path (string): Path to CSV
        delimiter (string): --delimiter, Field delimiter
        hostname_field (string): --hostname_field, Name of Colum where Hostname is found
    """
    #pylint: disable=no-member, consider-using-generator
    filename = csv_path.split('/')[-1]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"\
          f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field]
            print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
            host_obj = Host.get_host(hostname)
            del row[hostname_field]
            host_obj.set_labels(row)
            host_obj.set_import_seen()
            host_obj.set_account(f"csv_{filename}", filename)
            host_obj.save()

@_cli_csv.command('inventorize_hosts')
@click.argument("csv_path")
@click.option("--delimiter", default=';')
@click.option("--hostname_field", default='host')
@click.option("--key", default='csv')
def inventorize_hosts(csv_path, delimiter, hostname_field, key):
    """
    Add Inventory Information to hosts.
    Source is a CSV. Every other Column then the host Column, will translate
    into key:value attributes.

    Example
    =======
    _./cmdbsyncer csv inventorize_hosts path_to.csv --delimiter ';' --key "File1"_

    Args:
        csv_path (string): Path to CSV
        delimiter (string): --delimiter, Field delimiter
        hostname_field (string): --hostname_field, Name of Colum where Hostname is found
        key (string): --key, Group Name for Inventory data
    """
    #pylint: disable=no-member, consider-using-generator
    filename = csv_path.split('/')[-1]
    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC}"\
          f"{ColorCodes.UNDERLINE}{filename}{ColorCodes.ENDC}")
    new_attributes = {}
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=delimiter)
        for row in reader:
            hostname = row[hostname_field]
            print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Got Data for {hostname}")
            del row[hostname_field]
            new_attributes[hostname] = {f"{key}_{x}":y for x,y in row.items()}

    for host_obj in Host.objects(available=True):
        print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {host_obj.hostname}")
        host_obj.update_inventory(key, new_attributes.get(host_obj.hostname, {}))
        host_obj.save()
