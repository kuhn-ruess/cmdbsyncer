"""Jira Cloud plugin."""
import click
from application.plugins.jira import jira_cli

from syncerapi.v1 import (
    register_cronjob,
)

from .jira_cloud import import_jira_cloud
from .export import export_jira_cloud
from .schema_sync import sync_jira_schema

@jira_cli.command('import_cloud')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_import_jira(account, debug):
    """
    Import from Cloud Instance
    """
    try:
        import_jira_cloud(account, debug)
    except Exception as error:  # pylint: disable=broad-exception-caught
        if debug:
            raise
        print(f"Error: {error}")


@jira_cli.command('export_cloud')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_export_jira(account, debug):
    """
    Export Hosts/Fields to a Jira Cloud Assets Instance
    """
    try:
        export_jira_cloud(account, debug)
    except Exception as error:  # pylint: disable=broad-exception-caught
        if debug:
            raise
        print(f"Error: {error}")


@jira_cli.command('sync_schema')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_sync_jira_schema(account, debug):
    """
    Cache the Jira Cloud Assets schema (used by the export GUI / plugin)
    """
    try:
        sync_jira_schema(account, debug)
    except Exception as error:  # pylint: disable=broad-exception-caught
        if debug:
            raise
        print(f"Error: {error}")


register_cronjob('Jira Cloud: Import Hosts', import_jira_cloud)
register_cronjob('Jira Cloud: Export Objects', export_jira_cloud)
register_cronjob('Jira Cloud: Sync Schema', sync_jira_schema)
