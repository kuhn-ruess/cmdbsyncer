import click

from application import app
from application.helpers.cron import register_cronjob

from .mysql import mysql_import, mysql_inventorize

@app.cli.group(name='mysql')
def cli_mysql():
    """MYSQL Import/ Inventorize"""

@cli_mysql.command('import_hosts')
@click.argument('account')
def cli_mysql_import(account):
    """Import MysQL Hosts"""
    mysql_import(account)

@cli_mysql.command('inventorize_hosts')
@click.argument('account')
def cli_inventorize_hosts(account):
    """
    ## Add Inventory Information to hosts
    Source is a MYSQL. Every Column, will translate
    into key:value attributes.

    ### Example
    _./cmdbsyncer mysql inventorize_hosts ACCOUNTNAME"_

    """
    mysql_inventorize(account)

register_cronjob("Mysql: Import Hosts", mysql_import)
register_cronjob("Mysql: Inventorize Hosts", mysql_inventorize)