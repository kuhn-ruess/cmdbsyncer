
"""
Maintenance Module
"""
#pylint: disable=too-many-arguments
import datetime
import click
from application import app
from application.models.host import Host
from application.helpers.debug import ColorCodes
from application.helpers.poolfolder import remove_seat



@app.cli.command('maintenance')
@click.argument("days")
def maintenance(days):
    """Run maintenance tasks"""
    print(f"{ColorCodes.HEADER} ***** Run Tasks ***** {ColorCodes.ENDC}")
    print(f"{ColorCodes.UNDERLINE}Cleanup Hosts not found anymore{ColorCodes.ENDC}")
    now = datetime.datetime.now()
    delta = datetime.timedelta(int(days))
    timedelta = now - delta
    for host in Host.objects(available=False, last_import_seen=timedelta):
        print(f"{ColorCodes.WARNING}  ** {ColorCodes.ENDC}Deleted host {host.hostname}")
        if host.get_folder():
            folder = host.get_folder()
            remove_seat(folder)
            print(f"{ColorCodes.WARNING}  *** {ColorCodes.ENDC}Seat in Pool {folder} free now")
        host.delete()

