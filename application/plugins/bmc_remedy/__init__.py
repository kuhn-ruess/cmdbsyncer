"""BMC Remedy plugin."""
import click
from application import app
from application.helpers.plugins import register_cli_group

from syncerapi.v1 import (
    register_cronjob,
)

from .bmc_remedy import get_hosts

_cli_bmc_remedy = register_cli_group(app, 'bmc-remedy', 'bmc_remedy', "BMC Remedy Import")

@_cli_bmc_remedy.command('get_hosts')
@click.argument('account')
def cli_get_hosts(account):
    """Sync Hosts from Remedy"""
    get_hosts(account)


register_cronjob("BMC Remedy: Get Hosts", get_hosts)
