import click
from application import app

from syncerapi.v1 import register_cronjob

from .prtg import inventorize_prtg, import_prtg

@app.cli.group(name='prtg')
def prtg_cli():
    """PRTG Commands"""

@prtg_cli.command('inventorize_devices')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_inventorize_prtg(account, debug):
    """
    Inventorize Objects from PRTG Monitoring
    """
    try:
        inventorize_prtg(account, debug)
    except Exception as error:
        if debug:
            raise
        print(f"Error: {error}")

register_cronjob('PRTG Monitoring: Inventorize Objects', inventorize_prtg)

@prtg_cli.command('import_devices')
@click.argument("account")
@click.option("--debug", is_flag=True)
def cmd_import_prtg(account, debug):
    """
    Import Objects from PRTG Monitoring
    """
    try:
        import_prtg(account, debug)
    except Exception as error:
        if debug:
            raise
        print(f"Error: {error}")

register_cronjob('PRTG Monitoring: Import Objects', import_prtg)