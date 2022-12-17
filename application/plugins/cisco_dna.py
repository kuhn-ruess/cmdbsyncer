
"""
Cisco DNA Inventory
"""
#pylint: disable=too-many-arguments

import click
from application import app
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes
from application.modules.cisco_dna.syncer import CiscoDNA

@app.cli.group(name='cisco-dna')
def _cli_cisco_dna():
    """Cisco DNA related commands"""

if app.config.get("DISABLE_SSL_ERRORS"):
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3 import disable_warnings
    disable_warnings(InsecureRequestWarning)



#.
#   .-- CLI Commands
@_cli_cisco_dna.command('get_hosts')
@click.argument('account')
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

@_cli_cisco_dna.command('get_interfaces')
@click.argument('account')
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
