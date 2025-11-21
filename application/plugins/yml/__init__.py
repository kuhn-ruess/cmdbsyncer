import click
from application import app
from syncerapi.v1 import register_cronjob


from .yml import (
    import_hosts_yml,
    import_hosts_rest,
    inventorize_hosts_file,
    inventorize_hosts_rest
)

@app.cli.group(name='yml')
def _cli_yml():
    """YML Import"""

@_cli_yml.command('import_objects')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_import_hosts_yml(account, debug):
    """
    Import Hosts from YML File
    """
    import_hosts_yml(account, debug)

@_cli_yml.command('import_objects_rest')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_import_hosts_yml_rest(account, debug):
    """
    Import Hosts from YML via HTTP
    """
    import_hosts_rest(account, debug)

@_cli_yml.command('inventorize_objects_rest')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_inventorize_hosts_yml_rest(account, debug):
    """
    Inventorize Hosts from YML via HTTP
    """
    inventorize_hosts_rest(account, debug)

@_cli_yml.command('inventorize_objects_file')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_inventorize_hosts_yml_file(account, debug):
    """
    Inventorize Hosts from YML File
    """
    inventorize_hosts_file(account, debug)

register_cronjob('YML FILE: Import Hosts', import_hosts_yml)
register_cronjob('YML HTTP: Import Hosts', import_hosts_rest)
register_cronjob('YML HTTP: Inventorize Objects', inventorize_hosts_rest)
register_cronjob('YML FILE: Inventorize Objects', inventorize_hosts_file)
