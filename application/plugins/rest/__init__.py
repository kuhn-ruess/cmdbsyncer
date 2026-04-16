"""REST API plugin."""
import click
from application import app
from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group

from .rest import import_hosts_rest, inventorize_hosts_rest

_cli_rest = register_cli_group(app, 'rest', 'rest', "REST API related Commands")


@_cli_rest.command('import_hosts')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_import_hosts_rest(account, debug):
    """
    Import Json direct from Rest API
    """
    return import_hosts_rest(account, debug)

@_cli_rest.command('inventorize_objects')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_inventorize_hosts_rest(account, debug):
    """
    Import Json direct from Rest API
    """
    return inventorize_hosts_rest(account, debug)

register_cronjob('REST API: Import Objects', import_hosts_rest)
register_cronjob('REST API: Inventorize Objects', inventorize_hosts_rest)
