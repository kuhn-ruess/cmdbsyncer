import click
from application import app
from application.helpers.cron import register_cronjob

from .jira import import_jira

@app.cli.group(name='jira')
def jira_cli():
    """Jira commands"""

@jira_cli.command('import_onprem')
@click.argument("account")
def cmd_import_jira(account):
    """
    Import from On Premise Jira
    """
    import_jira(account)

register_cronjob('Jira OnPrem: Import  Hosts', import_jira)