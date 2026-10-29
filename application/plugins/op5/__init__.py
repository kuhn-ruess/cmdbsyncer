"""OP5 Monitor plugin."""
import click
from application import app
from application.helpers.plugins import register_cli_group

from syncerapi.v1 import register_cronjob

from .op5 import inventorize_op5, import_op5

op5_cli = register_cli_group(app, 'op5', 'op5', "OP5 Monitor Commands")

@op5_cli.command('import_hosts')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_import_op5(account, debug):
    """
    Import Hosts from OP5 Monitor
    """
    try:
        import_op5(account, debug)
    except Exception as error:  # pylint: disable=broad-exception-caught
        if debug:
            raise
        print(f"Error: {error}")

register_cronjob('OP5 Monitor: Import Hosts', import_op5)

@op5_cli.command('inventorize_hosts')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_inventorize_op5(account, debug):
    """
    Inventorize Hosts from OP5 Monitor
    """
    try:
        inventorize_op5(account, debug)
    except Exception as error:  # pylint: disable=broad-exception-caught
        if debug:
            raise
        print(f"Error: {error}")

register_cronjob('OP5 Monitor: Inventorize Hosts', inventorize_op5)
