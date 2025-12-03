import click

from syncerapi.v1 import (
    register_cronjob,
)
from syncerapi.v1.core import cli

from .pyodbc import ODBC

@cli.group(name='odbc')
def cli_odbc():
    """ODBC commands"""

def odbc_import(account, debug=False):
    """
    ODBC Inner Import
    """
    odbc = ODBC(account)
    odbc.name = f"Import data from {account}"
    odbc.source = "odbc_import"
    odbc.debug = debug
    odbc.sql_import()

@cli_odbc.command('import_hosts')
@click.option("--debug", default=False, is_flag=True)
@click.argument('account')
def cli_odbc_import(account, debug):
    """Import ODBC Hosts"""
    odbc_import(account, debug)


def odbc_inventorize(account, debug=False):
    """
    ODBC Inner Inventorize
    """
    odbc = ODBC(account)
    odbc.name = f"Inventorize data from {account}"
    odbc.source = "odbc_inventorize"
    odbc.debug = debug
    odbc.sql_inventorize()


@cli_odbc.command('inventorize_hosts')
@click.option("--debug", default=False, is_flag=True)
@click.argument('account')
def cli_odbc_inventorize(account, debug):
    """Inventorize ODBC Data"""
    odbc_inventorize(account, debug)

register_cronjob("ODBC: Import Hosts", odbc_import)
register_cronjob("ODBC: Inventorize Data", odbc_inventorize)