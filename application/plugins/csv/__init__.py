import click
from application import app
from application.helpers.cron import register_cronjob

from .csv import inventorize_hosts, import_hosts, compare_hosts

@app.cli.group(name='csv')
def _cli_csv():
    """CSV Import/ Inventorize"""

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

@_cli_csv.command('import_hosts')
@click.argument("csv_path", default="")
@click.option("--delimiter", default=';')
@click.option("--hostname_field", default='host')
@click.option("--account", default='')
def cli_import_hosts(csv_path, delimiter, hostname_field, account):
    """
    ## Import Objects from CSV and make File the Master
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