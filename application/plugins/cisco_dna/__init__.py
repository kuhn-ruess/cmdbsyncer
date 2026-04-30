
"""
Cisco DNA Inventory
"""

import click
from application import app
from application.helpers.get_account import get_account_by_name
from application.helpers.cron import register_cronjob
from application.helpers.plugins import register_cli_group
from application.modules.debug import ColorCodes

from .syncer import CiscoDNA

_cli_cisco_dna = register_cli_group(app, 'cisco-dna', 'cisco_dna',
                                    "Cisco DNA Interface and Devices")


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
    except Exception as error_obj:
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
    except Exception as error_obj:  # pylint: disable=broad-exception-caught
        print(f'C{ColorCodes.FAIL}Error: {error_obj} {ColorCodes.ENDC}')


@_cli_cisco_dna.command('get_interfaces')
@click.argument('account')
def cli_get_interfaces(account):
    """Sync Interfaces from DNA"""
    get_interfaces(account)



register_cronjob("Cisco DNA: Get Devices", get_hosts)
register_cronjob("Cisco DNA: Get Interfaces", get_interfaces)
