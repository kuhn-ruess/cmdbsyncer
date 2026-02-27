import click
from application import app
from application.helpers.cron import register_cronjob

from .csv import CSV

@app.cli.group(name='csv')
def _cli_csv():
    """CSV Import/ Inventorize"""

@_cli_csv.command('inventorize_hosts')
@click.argument("account", required=False)
@click.option("--debug", default=False, is_flag=True)
@click.option("--legacy", default=None, help="Path to CSV file for legacy mode (bypasses account config)")
def cli_inventorize_hosts(account, debug, legacy):
    """
    Add Inventory Information to hosts
    Source is a CSV. Every other Column then the hostname Column, will translate
    into key:value attributes.

    ### Example
    _./cmdbsyncer csv inventorize_hosts ACCOUNT_
    _./cmdbsyncer csv inventorize_hosts --legacy /path/to/file.csv_

    Args:
        account (string): Name of Account to read config from
        legacy (string): Path to CSV file for legacy mode
    """
    if legacy and account:
        click.echo("Error: Cannot use both account and --legacy option")
        return
    if not legacy and not account:
        click.echo("Error: Either account or --legacy option is required")
        return
    inventorize_hosts(account, debug, legacy)


def inventorize_hosts(account=None, debug=False, legacy=None):
    if legacy:
        csv = CSV()
        csv.config = _create_legacy_config(legacy)
        csv.account_name = "legacy"
        csv.account_id = "legacy"
    else:
        csv = CSV(account)
    csv.debug = debug
    csv.inventorize_hosts()



register_cronjob('CSV: Inventorize Hosts', inventorize_hosts)

@_cli_csv.command('import_hosts')
@click.argument("account", required=False)
@click.option("--debug", default=False, is_flag=True)
@click.option("--legacy", default=None, help="Path to CSV file for legacy mode (bypasses account config)")
def cli_import_hosts(account, debug, legacy):
    """
    Import Objects from CSV and make File the Master
    Every CSV column, other then the host column, will translate
    into key:value attributes.

    If you seet account as parameter, all config will be read from there

    ### Example
    _./cmdbsyncer csv import_hosts ACCOUNT_
    _./cmdbsyncer csv import_hosts --legacy /path/to/file.csv_

    Args:
        account (string): Name of Account to read config from
        legacy (string): Path to CSV file for legacy mode
    """
    if legacy and account:
        click.echo("Error: Cannot use both account and --legacy option")
        return
    if not legacy and not account:
        click.echo("Error: Either account or --legacy option is required")
        return
    import_hosts(account, debug, legacy)

def import_hosts(account=None, debug=False, legacy=None):
    if legacy:
        csv = CSV()
        csv.config = _create_legacy_config(legacy)
        csv.account_name = "legacy"
        csv.account_id = "legacy"
    else:
        csv = CSV(account)
    csv.debug = debug
    csv.import_hosts()

def _create_legacy_config(csv_path):
    """
    Create a minimal configuration for legacy mode
    
    Args:
        csv_path (string): Path to the CSV file
        
    Returns:
        dict: Minimal configuration dictionary
    """
    return {
        'name': 'legacy_csv',
        'id': 'legacy_csv',
        '_id': 'legacy_csv', 
        'path': csv_path,
        'encoding': 'utf-8',
        'delimiter': ';',
        'hostname_field': 'host',
        'rewrite_hostname': None,
        'delete_host_if_not_found_on_import': None,
        'verify_cert': True
    }

register_cronjob('CSV: Import Hosts', import_hosts)

@_cli_csv.command('compare_hosts')
@click.argument("csv_path", default="")
@click.option("--delimiter", default=';')
@click.option("--hostname_field", default='host')
@click.option("--label_filter", default='')
def cli_compare_hosts(csv_path, delimiter, hostname_field, label_filter):
    """
    Check which Hosts from your CSV are not in the syncer

    ### Example
    _./cmdbsyncer csv compare_hosts path_to.csv --delimiter ';'_

    Args:
        csv_path (string): Path to CSV
        delimiter (string): --delimiter, Field delimiter.
        hostname_field (string): --hostname_field, Name of Colum where Hostname is found.
        label_filter (string): --label_filter, Filder for given Labelname
    """
    csv = CSV()
    csv.compare_hosts(csv_path, delimiter, hostname_field, label_filter)