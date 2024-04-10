
"""
Maintenance Module
"""
#pylint: disable=too-many-arguments, logging-fstring-interpolation
import datetime
import string
import secrets
import click
from mongoengine.errors import DoesNotExist, ValidationError
from application import app, logger
from application.models.host import Host
from application.modules.debug import ColorCodes as CC
from application.modules.checkmk.poolfolder import remove_seat
from application.models.account import Account
from application.models.user import User
from application.modules.checkmk.models import CheckmkFolderPool
from application.models.config import Config
from application.helpers.cron import register_cronjob
from application.helpers.get_account import get_account_by_name



@app.cli.group(name='sys', short_help="Syncer commands")
def _cli_sys():
    """Syncer Commands

    This Group contains all syncer related commands
    """


#   .-- Command: Maintanence

def maintenance(account):
    """
    Inner Maintenance Mode
    """
    print(f"{CC.HEADER} ***** Run Tasks ***** {CC.ENDC}")

    account_filter = False
    account_filter_name = False

    # Hack: You could call the inital command without account,
    # so whe assume if we just get a Integer, this is the legacy mode,
    # else it's a account
    if isinstance(account, int):
        days = account
    else:
        account = get_account_by_name(account)
        days = int(account['delete_hosts_after_days'])
        account_filter_name = account.get('account_filter')
        if account_filter_name:
            account_filter = get_account_by_name(account_filter_name)

    if not days:
        print(f"{CC.WARNING} Days set to 0, exiting {CC.ENDC}")
        return

    print(f"{CC.UNDERLINE}Cleanup Hosts not found for {days} days," \
          f"Filter: {account_filter_name}{CC.ENDC}")

    now = datetime.datetime.now()
    delta = datetime.timedelta(days)
    timedelta = now - delta
    if account_filter:
        objects = Host.objects(last_import_seen__lte=timedelta,
                               source_account_id=str(account_filter['id']))
    else:
        objects = Host.objects(last_import_seen__lte=timedelta)
    for host in objects:
        print(f"{CC.WARNING}  ** {CC.ENDC}Deleted host {host.hostname}")
        if host.get_folder():
            folder = host.get_folder()
            remove_seat(folder)
            print(f"{CC.WARNING}  *** {CC.ENDC}Seat in Pool {folder} free now")
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

@_cli_sys.command('delete_cache')
@click.argument("days", cache_name="")
def delete_cache(cache_name):
    """
    Delete object Cache
    """
    print(f"{CC.HEADER} ***** Delete Cache ***** {CC.ENDC}")
    for host in Host.objects():
        logger.debug(f"Handling Host {host.hostname}")
        if cache_name:
            for key in list(host.cache.keys()):
                if key.lower().startswith(cache_name):
                    del host.cache[key]
        else:
            host.cache = {}
        host.save()
    print(f"{CC.OKGREEN}  ** {CC.ENDC}Done")

#.
#   .-- Command: Delete Caches

@_cli_sys.command('delete_inventory')
def delete_inventory():
    """
    Delete the inventory of all hosts
    """
    print(f"{CC.HEADER} ***** Delete Inventory ***** {CC.ENDC}")
    for host in Host.objects():
        logger.debug(f"Handling Host {host.hostname}")
        host.inventory = {}
        host.save()
    print(f"{CC.OKGREEN}  ** {CC.ENDC}Done")

#.
#   .-- Command: Delete all Hosts
@_cli_sys.command('delete_all_hosts')
@click.argument("account", default="")
def delete_all_hosts(account):
    """
    Deletes All hosts from DB
    """
    print(f"{CC.HEADER} ***** Delete Hosts ***** {CC.ENDC}")
    answer = input(f" - Enter 'y' and hit enter to procceed (Account Filter: {account}): ")
    if answer.lower() in ['y', 'z']:
        db_filter = {
        }
        if account:
            db_filter['inventory__syncer_account'] = account
        print(f"{CC.WARNING}  ** {CC.ENDC}Start deletion")
        Host.objects(**db_filter).delete()
    else:
        print(f"{CC.OKGREEN}  ** {CC.ENDC}Aborted")

#.
#   .-- Command: Reset Folder Pools
@_cli_sys.command('reset_folder_pools')
def reset_folder_pools():
    """
    Reset Folder Pools Usage
    """
    print(f"{CC.HEADER} Rested Pools {CC.ENDC}")
    print(" -> make sure to delete hosts from cmk after and resync")
    answer = input(" - Enter 'y' and hit enter to procceed: ")
    if answer.lower() in ['y', 'z']:
        print(f"{CC.WARNING}  ** {CC.ENDC}Start reset")
        for pool in CheckmkFolderPool.objects():
            print(f"      - {pool.folder_name}")
            pool.folder_seats_taken = 0
            pool.save()

        for host in Host.objects():
            host.folder = None
            host.save()
    else:
        print(f"{CC.OKGREEN}  ** {CC.ENDC}Aborted")

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
