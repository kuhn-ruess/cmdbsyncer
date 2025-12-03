import click
from application.helpers.cron import register_cronjob
from application import app

from .json import import_hosts_json

@app.cli.group(name='json')
def _cli_json():
    """JSON File Import/ Inventorize"""

@_cli_json.command('import_hosts')
@click.argument("account")
@click.option("--debug", default=False, is_flag=True)
def import_hosts(account, debug):
    """
    ## Import Hosts from JSON File
    """
    #pylint: disable=no-member, consider-using-generator
    import_hosts_json(account, debug)


register_cronjob('JSON FILE: Import Hosts', import_hosts_json)