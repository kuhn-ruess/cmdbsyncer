"""Jira On-Premise plugin."""
import click
from application import app
from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group

from .jira import import_jira

jira_cli = register_cli_group(app, 'jira', 'jira', "Jira commands")

@jira_cli.command('import_onprem')
@click.argument("account")
def cmd_import_jira(account):
    """
    Import from On Premise Jira
    """
    import_jira(account)

register_cronjob('Jira OnPrem: Import  Hosts', import_jira)
