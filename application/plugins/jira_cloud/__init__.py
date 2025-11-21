import click
from .jira_cloud import import_jira_cloud
from syncerapi.v1 import (
    register_cronjob,
)

from application.plugins.jira import jira_cli

@jira_cli.command('import_cloud')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_import_jira(account, debug):
    """
    Import from Cloud Instance
    """
    try:
        import_jira_cloud(account, debug)
    except Exception as error:
        if debug:
            raise
        print(f"Error: {error}")

register_cronjob('Jira Cloud: Import  Hosts', import_jira_cloud)