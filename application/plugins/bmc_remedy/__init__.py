import click
from application import app

from .bmc_remedy import get_hosts

from syncerapi.v1 import (
    register_cronjob,
)

@app.cli.group(name='bmc-remedy')
def _cli_bmc_remedy():
    """BMC Remedy Import"""

@_cli_bmc_remedy.command('get_hosts')
@click.argument('account')
def cli_get_hosts(account):
    """Sync Hosts from Remedy"""
    get_hosts(account)


register_cronjob("BMC Remedy: Get Hosts", get_hosts)