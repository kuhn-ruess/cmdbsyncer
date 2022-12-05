
"""
Maintenance Module
"""
#pylint: disable=too-many-arguments
import datetime
import string
import secrets
import click
from mongoengine.errors import DoesNotExist, ValidationError
from application import app
from application.models.host import Host
from application.modules.debug import ColorCodes
from application.modules.checkmk.poolfolder import remove_seat
from application.models.account import Account
from application.models.user import User
from application.modules.checkmk.models import CheckmkFolderPool
from application.models.config import Config



@app.cli.group(name='sys', short_help="Syncer commands")
def cli_sys():
    """Syncer Commands

    This Group contains all syncer related commands
    """


#   .-- Command: Maintanence
@cli_sys.command('maintenance')
@click.argument("days")
def maintenance(days):
    """Run maintenance tasks"""
    print(f"{ColorCodes.HEADER} ***** Run Tasks ***** {ColorCodes.ENDC}")
    print(f"{ColorCodes.UNDERLINE}Cleanup Hosts not found anymore{ColorCodes.ENDC}")
    now = datetime.datetime.now()
    delta = datetime.timedelta(int(days))
    timedelta = now - delta
    for host in Host.objects(last_import_seen=timedelta):
        print(f"{ColorCodes.WARNING}  ** {ColorCodes.ENDC}Deleted host {host.hostname}")
        if host.get_folder():
            folder = host.get_folder()
            remove_seat(folder)
            print(f"{ColorCodes.WARNING}  *** {ColorCodes.ENDC}Seat in Pool {folder} free now")
        host.delete()
#.
#   .-- Command: Delete all Hosts
@cli_sys.command('delete_all_hosts')
def delete_all_hosts():
    """
    Deletes All hosts from DB
    """
    print(f"{ColorCodes.HEADER} ***** Delete Hosts ***** {ColorCodes.ENDC}")
    answer = input(" - Enter 'y' and hit enter to procceed: ")
    if answer.lower() in ['y', 'z']:
        print(f"{ColorCodes.WARNING}  ** {ColorCodes.ENDC}Start deletion")
        for host in Host.objects():
            host.delete()
    else:
        print(f"{ColorCodes.OKGREEN}  ** {ColorCodes.ENDC}Aborted")

#.
#   .-- Command: Reset Folder Pools
@cli_sys.command('reset_folder_pools')
def delete_all_hosts():
    """
    Reset Folder Pools Usage
    """
    print(f"{ColorCodes.HEADER} ***** Restet Pools (make sure to delete hosts from cmk after and resync) ***** {ColorCodes.ENDC}")
    answer = input(" - Enter 'y' and hit enter to procceed: ")
    if answer.lower() in ['y', 'z']:
        print(f"{ColorCodes.WARNING}  ** {ColorCodes.ENDC}Start reset")
        for pool in CheckmkFolderPool.objects():
            print(f"      - {pool.folder_name}")
            pool.folder_seats_taken = 0
            pool.save()

        for host in Host.objects():
            host.folder = None
            host.save()
    else:
        print(f"{ColorCodes.OKGREEN}  ** {ColorCodes.ENDC}Aborted")

#.
#   .-- Command: Show Accounts
@cli_sys.command('show_accounts')
def show_accounts():
    """Print list of all active accounts"""

    for account in Account.objects(enabled=True):
        print(f"- Name: {account.name}, Type: {account.typ}, Address: {account.address}")

#.
#   .-- Command: Create User
@cli_sys.command('create_user')
@click.argument("email")
def seed_user(email):
    """Create new user or overwrite user password"""

    try:
        user = User.objects.get(email=email)
    except DoesNotExist:
        user = User()
        user.email = email

    alphabet = string.ascii_letters + string.digits
    passwd = ''.join(secrets.choice(alphabet) for i in range(20))
    user.set_password(passwd)
    user.global_admin = True
    user.tfa_secret = None
    user.disable = False
    try:
        user.save()
    except ValidationError:
        print(f"Invalid E-Mail: {email}")
        return 1
    print(f"User passwort set to: {passwd}")
    return 0
#.
#   .-- Command: Export Rules
#@cli_sys.command('export_rules')
#@click.argument("rule_model")
#def export_rules(rule_model):
#    """Export given Rule Model"""
#    models = [
#    ]
#
##.
#   .-- Command: self configure
@cli_sys.command('self_configure')
def self_configure():
    """Seed an Update system"""
    print("Seed data if needed:")
    if not len(Config.objects()):
        conf = Config()
        conf.save()
    print("- done")

##.
