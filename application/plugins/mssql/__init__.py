import click
from syncerapi.v1 import (
    register_cronjob,
)

from syncerapi.v1.core import (
    cli,
)

from application import app
from application.plugins.pyodbc import ODBC

@cli.group(name='mssql')
def cli_mssql():
    """Microsoft SQL Server Import/ Inventorize"""

#   . CLI and Cron
def mssql_import(account, debug=False):
    """
    MSSQL Inner Import
    """
    mssql = ODBC(account)
    mssql.name = f"Import data from {account}"
    mssql.source = "mssql_import"
    mssql.debug = debug
    mssql.sql_import()

@cli_mssql.command('import_hosts')
@click.option("--debug", default=False, is_flag=True)
@click.argument('account')
def cli_mssql_import(account, debug):
    """Import MSSQL Hosts"""
    mssql_import(account, debug)


def mssql_inventorize(account, debug=False):
    """
    MSSQL Inner Inventorize
    """
    mssql = ODBC(account)
    mssql.name = f"Inventorized data from {account}"
    mssql.source = "mssql_inventorize"
    mssql.debug = debug
    mssql.sql_inventorize()


@cli_mssql.command('inventorize_hosts')
@click.option("--debug", default=False, is_flag=True)
@click.argument('account')
def cli_mssql_inventorize(account, debug):
    """Inventorize MSSQL Data"""
    mssql_inventorize(account, debug)

register_cronjob("MsSQL: Import Hosts", mssql_import)
register_cronjob("MsSQL: Inventorize Data", mssql_inventorize)
#.