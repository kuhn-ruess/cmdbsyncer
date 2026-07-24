#!/usr/bin/env python3
"""
ServiceNow Import
"""
import click

from application import app
from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group

from .syncer import SyncServiceNow


_cli_servicenow = register_cli_group(app, 'ServiceNow', 'servicenow', "ServiceNow Import")


#   .-- Command: import hosts
def import_hosts(account, debug=False):
    """
    Import hosts from ServiceNow
    """
    syncer = SyncServiceNow(account)
    syncer.debug = debug
    syncer.import_hosts()


@_cli_servicenow.command('import_hosts')
@click.option("--account")
@click.option("--debug", default=False, is_flag=True)
def cli_import_hosts(account, debug):
    """
    Import hosts from ServiceNow
    """
    import_hosts(account, debug)
#.


register_cronjob('ServiceNow: Import hosts', import_hosts)
