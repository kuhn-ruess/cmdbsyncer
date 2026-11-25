"""
Run Jobs defined by Account: run the jobs the account lists
"""
import click

from application import app
from application.helpers.cron import register_cronjob
from application.helpers.account_jobs import ACCOUNT_JOBS_JOB, run_account_jobs


@app.cli.group(name='accounts')
def _cli_accounts():
    """Account commands"""


@_cli_accounts.command('run_jobs')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def cli_run_jobs(account, debug):
    """
    Run the jobs of the account in their order. Without jobs set, a main
    source or an account that is not limited imports, an additional
    source inventorizes.

    ### Example
    _./cmdbsyncer accounts run_jobs ACCOUNT_
    """
    run_account_jobs(account, debug)


register_cronjob(ACCOUNT_JOBS_JOB, run_account_jobs, first=True)
