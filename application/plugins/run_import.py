"""
Run Import: import or inventorize with an account, as its role says
"""
import click

from application import app
from application.helpers.cron import register_cronjob
from application.helpers.run_import import RUN_IMPORT_JOB, run_import


@app.cli.group(name='accounts')
def _cli_accounts():
    """Source account commands"""


@_cli_accounts.command('run_import')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_run_import(account, debug):
    """
    Import or inventorize with the account: a main source or an account
    without a role imports hosts, an additional source inventorizes.

    ### Example
    _./cmdbsyncer accounts run_import ACCOUNT_
    """
    run_import(account, debug)


register_cronjob(RUN_IMPORT_JOB, run_import, first=True)
