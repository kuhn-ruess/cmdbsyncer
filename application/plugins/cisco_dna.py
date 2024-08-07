
"""
Cisco DNA Inventory
"""
#pylint: disable=too-many-arguments

import click
from application import app
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes
from application.modules.cisco_dna.syncer import CiscoDNA
from application.helpers.cron import register_cronjob

@app.cli.group(name='cisco-dna')
def _cli_cisco_dna():
    """Cisco DNA Interface and Devices"""

if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)



#.
#   .-- CLI Commands
def get_hosts(account):
    """Sync Switches from DNA"""
    try:
        if target_config := get_account_by_name(account):
            job = CiscoDNA(target_config)
            job.get_hosts()
        else:
            print(f"{ColorCodes.FAIL} Target not found {ColorCodes.ENDC}")
    except Exception as error_obj: #pylint: disable=broad-except
        print(f'C{ColorCodes.FAIL}Error: {error_obj} {ColorCodes.ENDC}')
        raise

@_cli_cisco_dna.command('get_hosts')
@click.argument('account')
def cli_get_hosts(account):
    """Sync Switches from DNA"""
    get_hosts(account)


def get_interfaces(account):
    """Sync Interfaces from DNA"""
    try:
        if target_config := get_account_by_name(account):
            job = CiscoDNA(target_config)
            job.get_interfaces()
        else:
            print(f"{ColorCodes.FAIL} Target not found {ColorCodes.ENDC}")
    except Exception as error_obj: #pylint: disable=broad-except
        print(f'C{ColorCodes.FAIL}Error: {error_obj} {ColorCodes.ENDC}')


@_cli_cisco_dna.command('get_interfaces')
@click.argument('account')
def cli_get_interfaces(account):
    """Sync Interfaces from DNA"""
    get_interfaces(account)



register_cronjob("Cisco DNA: Get Devices", get_hosts)
register_cronjob("Cisco DNA: Get Interfaces", get_interfaces)
