
"""
Maintenance Module
"""
#pylint: disable=too-many-arguments, logging-fstring-interpolation
import os
import datetime
import string
import secrets
from pprint import pformat
from cryptography.fernet import Fernet
import click
from mongoengine.errors import DoesNotExist, ValidationError
from application import app, logger, log
from application.models.host import Host
from application.modules.debug import ColorCodes as CC
from application.plugins.checkmk.poolfolder import remove_seat
from application.models.account import Account
from application.models.user import User
from application.plugins.checkmk.models import CheckmkFolderPool
from application.models.config import Config
from application.helpers.cron import register_cronjob
from application.helpers.get_account import get_account_by_name



@app.cli.group(name='sys', short_help="Syncer commands")
def _cli_sys():
    """Syncer Commands

    This Group contains all syncer related commands
    """


#   .-- Command: Maintenance

def maintenance(account):
    """
    Inner Maintenance Mode
    """
    print(f"{CC.HEADER} ***** Run Tasks ***** {CC.ENDC}")
    details = []

    account_filter = False
    account_filter_name = False
    dont_delete_if_more = False

    # Hack: You could call the inital command without account,
    # so whe assume if we just get a Integer, this is the legacy mode,
    # else it's a account
    if isinstance(account, int):
        days = account
    else:
        account = get_account_by_name(account)
        days = int(account['delete_hosts_after_days'])
        account_filter_name = account.get('account_filter')
        dont_delete_if_more = account.get('dont_delete_hosts_if_more_then')
        if account_filter_name:
            account_filter = get_account_by_name(account_filter_name)

    if not days:
        print(f"{CC.WARNING} Days set to 0, exiting {CC.ENDC}")
        return

    print(f"{CC.UNDERLINE}Cleanup Hosts not found for {days} days, " \
          f"Filter: {account_filter_name}{CC.ENDC}")

    now = datetime.datetime.now()
    delta = datetime.timedelta(days)
    timedelta = now - delta
    if account_filter:
        objects = Host.objects(last_import_seen__lte=timedelta,
                               source_account_id=str(account_filter['id']), no_autodelete__ne=True, object_type__ne = 'template')
    else:
        objects = Host.objects(last_import_seen__lte=timedelta, no_autodelete__ne=True, object_type__ne = 'template')

    if dont_delete_if_more:
        if int(dont_delete_if_more) >= len(objects):
            details.append(
                (
                    'error',
                    "Hosts were not deleted because their number "
                    "exceeds the configured threshold."
                )
            )
            objects = []

    deleted_hosts = 0
    for host in objects:
        print(f"{CC.WARNING}  ** {CC.ENDC}Deleted host {host.hostname}")
        if host.get_folder():
            folder = host.get_folder()
            remove_seat(folder)
            print(f"{CC.WARNING}  *** {CC.ENDC}Seat in Pool {folder} free now")
        host.delete()
        deleted_hosts += 1
    details.append(('hosts_deleted', deleted_hosts))
    log.log(f"Database Maintenance {account}",
            source="Maintenance", details=details)

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
@click.argument("cache_name", default="")
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
#   .-- Command: Delete Inventory

@_cli_sys.command('delete_inventory')
@click.argument("prefix_only", default="")
def delete_inventory(prefix_only):
    """
    Delete the inventory of all hosts

    Add a prefix als parameter to limit to only the ones starting with that
    """
    print(f"{CC.HEADER} ***** Delete Inventory ***** {CC.ENDC}")
    for host in Host.objects():
        logger.debug(f"Handling Host {host.hostname}")
        if prefix_only:
            prefix_only = prefix_only.lower()
            for entry in list(host.inventory.keys()):
                if entry.lower().startswith(prefix_only):
                    del host.inventory[entry]
        else:
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
        db_filter = {'no_autodelete__ne': True, 'object_type__ne': "template"}
        if account:
            db_filter['source_account_name'] = account
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
        print(f"- Name: {account.name}, Type: {account.type}, Address: {account.address}")


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
        user.name = email.split('@')[0]

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
    print(f"User password set to: {passwd}")
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


def migrate_accounts(old_key, new_key):
    """
    There where Setups which did updates without running self_configure
    Depending on their fernet module version, there in the situation that all
    theirs Accout Passwords where encrypted with the old key, 
    while the key need to be replaced with a new one.
    """
    for account in Account.objects():
        if account.password_crypted:
            password = account.get_password(old_key)
            account.set_password(password, new_key)


@_cli_sys.command('self_configure')
def self_configure():
    """
    Seed needed DB Changes or cleanup stuff.
    Use if stated in docs after Update.
    """
    print("Check for default Config Object")
    if not Config.objects():
        print(" -> Created")
        conf = Config()
        conf.save()
    else:
        print(" -> Existed")


    print("Check for local_config.py File")
    if not os.path.isfile('local_config.py'):
        with open('local_config.py', 'w', encoding="utf-8") as lf:
            lf.write("#!/usr/bin/env python3\n")
            lf.write('"""\nLocal Config File\n"""\n')
            lf.write("import logging\n")
            lf.write("# Only Update from here inside the config = {} object\n")
            lf.write("config = {}\n")
        print(" -> Created new local_config.py")
    else:
        print(" -> Existed")

    print("Seed missing Default Values to the local_config.py")
    alphabet = string.ascii_letters + string.digits + string.punctuation
    values = {
        'SECRET_KEY': ''.join(secrets.choice(alphabet) for i in range(120)),
        'CRYPTOGRAPHY_KEY' : Fernet.generate_key(),
        'SESSION_COOKIE_NAME': "cmdb-syncer",
    }
    from local_config import config #pylint: disable=import-outside-toplevel
    for key, value in values.items():
        if key not in config:
            config[key] = value
    if not isinstance(config['CRYPTOGRAPHY_KEY'], bytes):
        old_key = config['CRYPTOGRAPHY_KEY']
        new_key = values['CRYPTOGRAPHY_KEY']
        migrate_accounts(old_key, new_key)

        config['CRYPTOGRAPHY_KEY'] = new_key
    with open('local_config.py', 'w', encoding="utf-8") as lf:
        lf.write("#!/usr/bin/env python3\n")
        lf.write('"""\nLocal Config File\n"""\n')
        lf.write("import logging\n")
        lf.write("# Only Update from here inside the config = {} object\n")
        lf.write(f"config = {pformat(config)}\n")

    # Migrate Users
    print("Migrate users")
    User.migrate_missing_names()

#.
register_cronjob("Syncer: Maintenence", maintenance)
