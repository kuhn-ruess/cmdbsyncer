#!/usr/bin/env python3
"""Import mssl Data"""
#pylint: disable=logging-fstring-interpolation
import click
from syncerapi.v1 import (
    register_cronjob,
)

from syncerapi.v1.core import (
    cli,
)

from application.plugins.pyodbc import ODBC

@cli.group(name='mssql')
def cli_mssql():
    """Microsoft SQL Server Import/ Inventorize"""


#   . CLI and Cron
def mssql_import(account):
    """
    MSSQL Inner Import
    """
    mssql = ODBC(account)
    mssql.name = f"Import data from {account}"
    mssql.source = "mssql_import"
    mssql.sql_import()

@cli_mssql.command('import_hosts')
@click.argument('account')
def cli_mssql_import(account):
    """Import MSSQL Hosts"""
    mssql_import(account)


def mssql_inventorize(account):
    """
    MSSQL Inner Inventorize
    """
    mssql = ODBC(account)
    mssql.name = f"Inventorized data from {account}"
    mssql.source = "mssql_inventorize"
    mssql.sql_inventorize()


@cli_mssql.command('inventorize_hosts')
@click.argument('account')
def cli_mssql_inventorize(account):
    """Inventorize MSSQL Data"""
    mssql_inventorize(account)

register_cronjob("MsSQL: Import Hosts", mssql_import)
register_cronjob("MsSQL: Inventorize Data", mssql_inventorize)
#.
