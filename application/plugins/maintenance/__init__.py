
"""
Maintenance Module
"""
import os
import datetime
import shutil
import string
import secrets
import subprocess
from pathlib import Path
from pprint import pformat
from cryptography.fernet import Fernet
import click
from mongoengine.errors import DoesNotExist, ValidationError
from application import app, logger, log
from application._version import __version__ as _SYNCER_VERSION
from application.models.host import Host
from application.modules.debug import ColorCodes as CC
from application.plugins.checkmk.poolfolder import remove_seat
from application.models.account import Account
from application.models.user import User
from application.plugins.checkmk.models import CheckmkFolderPool
from application.models.config import Config
from application.helpers.cron import register_cronjob
from application.helpers.get_account import get_account_by_name
from application.helpers.plugins import register_cli_group


_cli_sys = register_cli_group(app, 'sys', 'maintenance', "Syncer Commands")


_DEFAULT_APP_WSGI = '''\
#!/usr/bin/env python3
"""
WSGI entry point for CMDBsyncer.

Used by:
- gunicorn  (Docker image: `gunicorn ... application:app`)
- Apache + mod_wsgi (`WSGIScriptAlias / .../app.wsgi`, expects `application`)
- uWSGI (`wsgi-file = .../app.wsgi`, `callable = app`)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

if 'config' not in os.environ:
    os.environ['config'] = 'prod'

from application import app  # noqa: E402  pylint: disable=wrong-import-position
application = app
'''


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
                               source_account_id=str(account_filter['id']),
                               no_autodelete__ne=True,
                               object_type__ne='template',
                               deleted_at__exists=False)
    else:
        objects = Host.objects(last_import_seen__lte=timedelta,
                               no_autodelete__ne=True,
                               object_type__ne='template',
                               deleted_at__exists=False)

    if dont_delete_if_more:
        if len(objects) >= int(dont_delete_if_more):
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
        print(f"{CC.WARNING}  ** {CC.ENDC}Archived host {host.hostname}")
        if host.get_folder():
            folder = host.get_folder()
            remove_seat(folder)
            print(f"{CC.WARNING}  *** {CC.ENDC}Seat in Pool {folder} free now")
        host.soft_delete(reason=f"maintenance: not seen for {days} days")
        host.save()
        deleted_hosts += 1
    details.append(('hosts_archived', deleted_hosts))
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
#   .-- Command: Mark Stale

def mark_stale(account):
    """
    Walk one account's hosts and flip `is_stale` based on the account's
    `stale_after_days`. When the account also enables
    `auto_archive_when_stale`, stale hosts are soft-deleted so they
    leave the active fleet but stay restorable from the Archive view.

    Skips quietly when `stale_after_days` is 0 / unset.
    """
    print(f"{CC.HEADER} ***** Mark Stale ({account}) ***** {CC.ENDC}")
    details = []

    acc = get_account_by_name(account)
    try:
        days = int(acc.get('stale_after_days') or 0)
    except (TypeError, ValueError):
        days = 0
    if not days:
        print(f"{CC.WARNING} stale_after_days not configured, skipping {CC.ENDC}")
        return
    auto_archive = bool(acc.get('auto_archive_when_stale'))

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    base = {
        'source_account_id': str(acc['id']),
        'no_autodelete__ne': True,
        'object_type__ne': 'template',
        'deleted_at__exists': False,
    }

    stale_q = Host.objects(last_import_seen__lte=cutoff, is_stale__ne=True, **base)
    fresh_q = Host.objects(last_import_seen__gt=cutoff, is_stale=True, **base)
    marked = stale_q.update(set__is_stale=True, set__stale_since=cutoff)
    cleared = fresh_q.update(set__is_stale=False, set__stale_since=None)
    details.append(('hosts_marked_stale', marked))
    details.append(('hosts_cleared_stale', cleared))

    archived = 0
    if auto_archive:
        for host in Host.objects(is_stale=True, **base):
            host.soft_delete(reason=f"stale > {days} days")
            host.save()
            archived += 1
    details.append(('hosts_auto_archived', archived))

    print(f"{CC.OKGREEN}  ** {CC.ENDC}stale={marked}, cleared={cleared}, "
          f"auto-archived={archived}")
    log.log(f"Mark Stale {account}", source="Maintenance", details=details)


@_cli_sys.command('mark_stale')
@click.argument('account')
@click.option('--debug', is_flag=True)
def cli_mark_stale(account, debug):  # pylint: disable=unused-argument
    """
    Mark hosts of ACCOUNT as stale based on the account's
    `stale_after_days` custom field. With `auto_archive_when_stale`
    enabled the stale rows are also archived.
    """
    mark_stale(account)
#.
#   .-- Command: Delete Caches

def clear_host_caches(cache_name=""):
    """
    Clear the cache dict on all Host objects.

    If cache_name is given, only cache keys starting with that prefix
    (case-insensitive) are removed. Otherwise the full cache is reset.
    Uses atomic updates to bypass full-document validation.
    """
    if not cache_name:
        Host.objects(cache__ne={}).update(set__cache={})
        return
    prefix = cache_name.lower()
    for host in Host.objects(cache__ne={}):
        new_cache = {k: v for k, v in host.cache.items()
                     if not k.lower().startswith(prefix)}
        if new_cache != host.cache:
            host.update(set__cache=new_cache)


@_cli_sys.command('delete_cache')
@click.argument("cache_name", default="")
def delete_cache(cache_name):
    """
    Delete object Cache
    """
    print(f"{CC.HEADER} ***** Delete Cache ***** {CC.ENDC}")
    clear_host_caches(cache_name)
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
        logger.debug("Handling Host %s", host.hostname)
        if prefix_only:
            prefix = prefix_only.lower()
            new_inventory = {k: v for k, v in host.inventory.items()
                             if not k.lower().startswith(prefix)}
        else:
            new_inventory = {}
        host.update(set__inventory=new_inventory)
    print(f"{CC.OKGREEN}  ** {CC.ENDC}Done")

#.
#   .-- Command: Update CMDB Templates

@_cli_sys.command('update_cmdb')
def update_cmdb():
    """
    Updats Templates on all Hosts in Database
    """
    print(f"{CC.HEADER} ***** Update Templates ***** {CC.ENDC}")
    for host in Host.get_export_hosts():
        logger.debug("Handling Host %s", host.hostname)
        host.get_cmdb_template()
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

        raw_match = {
            "no_autodelete": {"$ne": True},
            "object_type": {"$ne": "template"},
        }
        if account:
            raw_match['source_account_name'] = account
        pipline = [
            {
                "$match": raw_match
            },
            {
                "$group": {
                    "_id" : "$folder",
                    "count": {"$sum": 1},
                }
            }
        ]
        for folder_pool in Host.objects.aggregate(*pipline):
            if folder_name := folder_pool['_id']:
                count = folder_pool['count']
                folder = CheckmkFolderPool.objects.get(folder_name__iexact=folder_name)
                if folder.folder_seats_taken > count:
                    folder.folder_seats_taken -= count
                else:
                    folder.folder_seats_taken = 0
                folder.save()
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
    user.disabled = False
    try:
        user.save()
    except ValidationError:
        print(f"Invalid E-Mail: {email}")
        return 1
    print(f"User password set to: {passwd}")
    return 0
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


def _ensure_local_config():
    """Create a stub local_config.py if missing."""
    print("Check for local_config.py File")
    if os.path.isfile('local_config.py'):
        print(" -> Existed")
        return
    with open('local_config.py', 'w', encoding="utf-8") as lf:
        lf.write("#!/usr/bin/env python3\n")
        lf.write('"""\nLocal Config File\n"""\n')
        lf.write("import logging\n")
        lf.write("# Only Update from here inside the config = {} object\n")
        lf.write("config = {}\n")
    print(" -> Created new local_config.py")


def _ensure_plugins_dir():
    """Create plugins/ as a Python package if missing."""
    print("Check for plugins/ directory")
    if not os.path.isdir('plugins'):
        os.makedirs('plugins')
        with open('plugins/__init__.py', 'w', encoding="utf-8") as pf:
            pf.write('"""Local plugins package."""\n')
        print(" -> Created new plugins/ directory")
    elif not os.path.isfile('plugins/__init__.py'):
        with open('plugins/__init__.py', 'w', encoding="utf-8") as pf:
            pf.write('"""Local plugins package."""\n')
        print(" -> Added missing plugins/__init__.py")
    else:
        print(" -> Existed")


def _ensure_app_wsgi():
    """Drop a default app.wsgi so Apache/mod_wsgi or uWSGI can serve a
    pip install out of the box. Existing files (Git checkout, Docker
    image) are left untouched."""
    print("Check for app.wsgi entry point")
    if os.path.isfile('app.wsgi'):
        print(" -> Existed")
        return
    with open('app.wsgi', 'w', encoding="utf-8") as wf:
        wf.write(_DEFAULT_APP_WSGI)
    print(" -> Created new app.wsgi")


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

    _ensure_local_config()
    _ensure_plugins_dir()
    _ensure_app_wsgi()

    print("Seed missing Default Values to the local_config.py")
    alphabet = string.ascii_letters + string.digits + string.punctuation
    values = {
        'SECRET_KEY': ''.join(secrets.choice(alphabet) for i in range(120)),
        'CRYPTOGRAPHY_KEY' : Fernet.generate_key(),
        'SESSION_COOKIE_NAME': "cmdb-syncer",
    }
    from local_config import config  # pylint: disable=import-outside-toplevel
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
#   .-- Command: Install default Ansible playbooks
@_cli_sys.command('install_playbooks')
@click.argument('target', type=click.Path(file_okay=False, resolve_path=True))
@click.option('--version', default=None,
              help="Git ref to fetch. Defaults to tag v<installed-version>.")
@click.option('--repo', default='https://github.com/kuhn-ruess/cmdbsyncer',
              show_default=True,
              help="Source repository for the playbooks.")
@click.option('--force', is_flag=True,
              help="Overwrite TARGET if it already exists.")
def install_playbooks(target, version, repo, force):
    """
    Copy the default Ansible playbooks, roles and inventory helpers
    into TARGET. Intended for pip installs of cmdbsyncer, where the
    Python package does not ship the playbook sources.

    Example: cmdbsyncer sys install_playbooks /opt/cmdbsyncer/ansible
    """
    print(f"{CC.HEADER} ***** Install Ansible playbooks ***** {CC.ENDC}")
    dest = Path(target)
    if dest.exists():
        if not force:
            print(f"{CC.FAIL}Refusing to overwrite existing {dest} "
                  f"(use --force).{CC.ENDC}")
            raise SystemExit(1)
        shutil.rmtree(dest)

    # Strip any LTS suffix (e.g. "3.12.13-LTS4") — the upstream tag is
    # always the plain v<major>.<minor>.<patch>.
    if not version:
        version = f"v{_SYNCER_VERSION.split('-', 1)[0]}"

    tmp = dest.with_suffix('.clone.tmp')
    if tmp.exists():
        shutil.rmtree(tmp)

    print(f"{CC.OKBLUE}  * {CC.ENDC}Cloning {repo} @ {version} …")
    try:
        subprocess.check_call(
            ['git', 'clone', '--depth', '1', '--filter=blob:none',
             '--no-checkout', '--branch', version, repo, str(tmp)],
        )
        subprocess.check_call(
            ['git', '-C', str(tmp), 'sparse-checkout', 'init', '--cone'],
        )
        subprocess.check_call(
            ['git', '-C', str(tmp), 'sparse-checkout', 'set', 'ansible'],
        )
        subprocess.check_call(['git', '-C', str(tmp), 'checkout'])
    except subprocess.CalledProcessError as exp:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"{CC.FAIL}Clone failed: {exp}{CC.ENDC}")
        raise SystemExit(1) from exp

    ansible_src = tmp / 'ansible'
    if not ansible_src.is_dir():
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"{CC.FAIL}Source {repo}@{version} has no ansible/ folder "
              f"— wrong branch?{CC.ENDC}")
        raise SystemExit(1)

    shutil.move(str(ansible_src), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{CC.OKGREEN}  ** {CC.ENDC}Installed to {dest}")
    print(f"{CC.OKGREEN}  ** {CC.ENDC}Install Ansible deps from the repo root: "
          f"pip install -r requirements-ansible.txt")

#.
register_cronjob("Syncer: Maintenence", maintenance)
register_cronjob("Syncer: Mark Stale Hosts", mark_stale)
