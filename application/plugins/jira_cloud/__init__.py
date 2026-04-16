"""Jira Cloud plugin."""
import click
from application.plugins.jira import jira_cli

from syncerapi.v1 import (
    register_cronjob,
)

from .jira_cloud import import_jira_cloud

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

register_cronjob('Jira Cloud: Import  Hosts', import_jira_cloud)
