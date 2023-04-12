
"""
Maintenance Module
"""
#pylint: disable=too-many-arguments
import datetime
import string
import secrets
import click
from mongoengine.errors import DoesNotExist, ValidationError
from application import app, logger
from application.models.host import Host
from application.modules.debug import ColorCodes
from application.modules.checkmk.poolfolder import remove_seat
from application.models.account import Account
from application.models.user import User
from application.modules.checkmk.models import CheckmkFolderPool
from application.models.config import Config
from application.helpers.cron import register_cronjob



@app.cli.group(name='sys', short_help="Syncer commands")
def _cli_sys():
    """Syncer Commands

    This Group contains all syncer related commands
    """


#   .-- Command: Maintanence

def maintenance(days):
    print(f"{ColorCodes.HEADER} ***** Run Tasks ***** {ColorCodes.ENDC}")
    print(f"{ColorCodes.UNDERLINE}Cleanup Hosts not found anymore{ColorCodes.ENDC}")
    now = datetime.datetime.now()
    delta = datetime.timedelta(int(days))
    timedelta = now - delta
    for host in Host.objects(last_import_seen__lte=timedelta):
        print(f"{ColorCodes.WARNING}  ** {ColorCodes.ENDC}Deleted host {host.hostname}")
        if host.get_folder():
            folder = host.get_folder()
            remove_seat(folder)
            print(f"{ColorCodes.WARNING}  *** {ColorCodes.ENDC}Seat in Pool {folder} free now")
        host.delete()

@_cli_sys.command('maintenance')
@click.argument("days", default=7)
def cli_maintenance(days):
    """
    Run maintenance tasks
    This includes deletion of old hosts.

    Args:
        days (int): Gracetime before host is deleted
    """
    maintenance(days)
#.
#   .-- Command: Delete Caches

if app.config['USE_CACHE']:
    @_cli_sys.command('delete_cache')
    def delete_cache():
        """
        Delete object Cache
        """
        print(f"{ColorCodes.HEADER} ***** Delete Cache ***** {ColorCodes.ENDC}")
        for host in Host.objects():
            logger.debug(f"Handling Host {host.hostname}")
            host.cache = {}
            host.save()
        print(f"{ColorCodes.OKGREEN}  ** {ColorCodes.ENDC}Done")

#.
#   .-- Command: Delete all Hosts
@_cli_sys.command('delete_all_hosts')
def delete_all_hosts():
    """
    Deletes All hosts from DB
    """
    print(f"{ColorCodes.HEADER} ***** Delete Hosts ***** {ColorCodes.ENDC}")
    answer = input(" - Enter 'y' and hit enter to procceed: ")
    if answer.lower() in ['y', 'z']:
        print(f"{ColorCodes.WARNING}  ** {ColorCodes.ENDC}Start deletion")
        for host in Host.objects():
            logger.debug(f"Handling Host {host.hostname}")
            host.delete()
    else:
        print(f"{ColorCodes.OKGREEN}  ** {ColorCodes.ENDC}Aborted")

#.
#   .-- Command: Reset Folder Pools
@_cli_sys.command('reset_folder_pools')
def reset_folder_pools():
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
@_cli_sys.command('show_accounts')
def show_accounts():
    """Print list of all active accounts"""

    for account in Account.objects(enabled=True):
        print(f"- Name: {account.name}, Type: {account.typ}, Address: {account.address}")

#.
#   .-- Command: Create User
@_cli_sys.command('create_user')
@click.argument("email")
def seed_user(email):
    """
    Create new user or overwrite user password

    Args:
        email (string): E-Mail Address of User

    """

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
#@_cli_sys.command('export_rules')
#@click.argument("rule_model")
#def export_rules(rule_model):
#    """Export given Rule Model"""
#    models = [
#    ]
#
#.
#   .-- Command: self configure
@_cli_sys.command('self_configure')
def self_configure():
    """
    Seed needed DB Changes or cleanup stuff.
    Use if stated in docs after Update.
    """
    print("Seed data if needed:")
    if not Config.objects():
        conf = Config()
        conf.save()
    print("- done")

#.
register_cronjob("Syncer: Maintanence", maintenance)
