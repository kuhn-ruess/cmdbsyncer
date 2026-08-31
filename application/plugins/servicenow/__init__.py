#!/usr/bin/env python3
"""
ServiceNow Import
"""
import click

from application import app
from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group

from .syncer import SyncServiceNow


_cli_servicenow = register_cli_group(app, 'service_now', 'servicenow', "ServiceNow Import")


#   .-- Command: import hosts
def import_hosts(account, debug=False):
    """
    Import hosts from ServiceNow
    """
    syncer = SyncServiceNow(account)
    syncer.debug = debug
    syncer.import_hosts()


@_cli_servicenow.command('import_hosts')
@click.argument('account')
@click.option("--debug", default=False, is_flag=True)
def cli_import_hosts(account, debug):
    """
    Import hosts from ServiceNow
    """
    import_hosts(account, debug)
#.


#   .-- Command: inventorize data
def inventorize_data(account, debug=False):
    """
    Attach ServiceNow records to the hosts they belong to
    """
    syncer = SyncServiceNow(account)
    syncer.debug = debug
    syncer.inventorize_data()


@_cli_servicenow.command('inventorize_data')
@click.argument('account')
@click.option("--debug", default=False, is_flag=True)
def cli_inventorize_data(account, debug):
    """
    Attach ServiceNow records to the hosts they belong to
    """
    inventorize_data(account, debug)
#.


register_cronjob('ServiceNow: Import hosts', import_hosts)
register_cronjob('ServiceNow: Inventorize data', inventorize_data)
