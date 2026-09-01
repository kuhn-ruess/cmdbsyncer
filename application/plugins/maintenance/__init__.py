
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
from application.helpers.stale_indexes import drop_stale_indexes
from application.helpers.get_account import get_account_by_name
from application.helpers.retention import sync_all
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

# Default retention for archived (soft-deleted) hosts before they are
# permanently removed. Overridable per account via the
# `purge_archived_after_days` custom field; 0 disables the purge.
DEFAULT_PURGE_ARCHIVED_DAYS = 30


def _resolve_purge_days(account):
    """
    Days after which archived hosts are permanently deleted. Reads the
    account's `purge_archived_after_days` override, falling back to
    DEFAULT_PURGE_ARCHIVED_DAYS when unset. Returns 0 when explicitly
    disabled. The legacy int-mode (no account) always uses the default.
    """
    raw = account.get('purge_archived_after_days') if isinstance(account, dict) else None
    if raw in (None, ''):
        return DEFAULT_PURGE_ARCHIVED_DAYS
    return int(raw)


def _purge_archived_hosts(account_filter, purge_days):
    """
    Permanently delete hosts that have been archived (soft-deleted) for
    longer than `purge_days` days. Protected (`no_autodelete`) hosts and
    templates are never purged. When an account filter is given the purge is
    scoped to that source account, mirroring the archiving step above.

    Returns the number of hosts removed.
    """
    if not purge_days:
        print(f"{CC.WARNING} Archive purge disabled (0 days) {CC.ENDC}")
        return 0

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=purge_days)
    db_filter = {
        'deleted_at__lte': cutoff,
        'no_autodelete__ne': True,
        'object_type__ne': 'template',
    }
    if account_filter:
        db_filter['source_account_id'] = str(account_filter['id'])

    print(f"{CC.UNDERLINE}Purge archived hosts older than {purge_days} days"
          f"{CC.ENDC}")
    purged = 0
    # Materialize before deleting so removing documents doesn't disturb the
    # cursor we're iterating.
    for host in list(Host.objects(**db_filter)):
        print(f"{CC.FAIL}  ** {CC.ENDC}Permanently deleting {host.hostname}")
        host.delete()
        purged += 1
    return purged


def _archive_unseen_hosts(days, account_filter, account_filter_name,
                          dont_delete_if_more, details):
    """
    Soft-delete every host its source has not reported for `days` days,
    freeing the Checkmk pool seat it held. Protected hosts, templates
    and already-archived hosts are left alone; with
    `dont_delete_hosts_if_more_then` set, a run that would archive more
    than the threshold archives nothing and says so in `details`.

    Returns the number of hosts archived.
    """
    print(f"{CC.UNDERLINE}Cleanup Hosts not found for {days} days, " \
          f"Filter: {account_filter_name}{CC.ENDC}")

    cutoff = datetime.datetime.now() - datetime.timedelta(days)
    db_filter = {
        'last_import_seen__lte': cutoff,
        'no_autodelete__ne': True,
        'object_type__ne': 'template',
        'deleted_at__exists': False,
    }
    if account_filter:
        db_filter['source_account_id'] = str(account_filter['id'])
    objects = Host.objects(**db_filter)

    if dont_delete_if_more and len(objects) >= int(dont_delete_if_more):
        details.append((
            'error',
            "Hosts were not deleted because their number "
            "exceeds the configured threshold."
        ))
        return 0

    archived = 0
    for host in objects:
        print(f"{CC.WARNING}  ** {CC.ENDC}Archived host {host.hostname}")
        if folder := host.get_folder():
            remove_seat(folder)
            print(f"{CC.WARNING}  *** {CC.ENDC}Seat in Pool {folder} free now")
        host.soft_delete(reason=f"maintenance: not seen for {days} days")
        host.save()
        archived += 1
    return archived


def _purge_orphaned_inventory_trees():
    """
    Delete inventory trees whose host no longer exists.

    ``HostInventoryTree`` is keyed by hostname, not by a Host reference,
    so a deleted host leaves its tree behind — and those trees are the
    large documents. Only the archive's bulk delete cleaned up after
    itself; everything else (the archive purge above, delete_all_hosts,
    a single delete) left orphans.

    Returns the number of trees removed.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host_inventory_tree import HostInventoryTree
    tree_names = set(HostInventoryTree.objects.distinct('hostname'))
    if not tree_names:
        return 0
    alive = set(Host.objects(hostname__in=list(tree_names)).distinct('hostname'))
    orphans = tree_names - alive
    if not orphans:
        return 0
    print(f"{CC.UNDERLINE}Remove inventory trees without a host{CC.ENDC}")
    for hostname in sorted(orphans):
        print(f"{CC.WARNING}  ** {CC.ENDC}Removing inventory tree of {hostname}")
    return HostInventoryTree.objects(hostname__in=list(orphans)).delete()


def _purge_orphaned_field_approvals():
    """
    Close field approvals whose host no longer exists.

    ``FieldApproval`` is keyed by hostname, and only decided entries
    expire — a pending one for a deleted host would sit in the queue
    forever and keep counting towards the "pending" badge. Rejecting
    rather than deleting keeps the decision trail and lets the existing
    TTL clear them on schedule.

    Returns the number of approvals closed.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.field_approval import FieldApproval
    names = set(FieldApproval.objects(status='pending').distinct('hostname'))
    if not names:
        return 0
    alive = set(Host.objects(hostname__in=list(names)).distinct('hostname'))
    orphans = names - alive
    if not orphans:
        return 0
    print(f"{CC.UNDERLINE}Close field approvals without a host{CC.ENDC}")
    for hostname in sorted(orphans):
        print(f"{CC.WARNING}  ** {CC.ENDC}Rejecting open approvals of {hostname}")
    return FieldApproval.objects(
        hostname__in=list(orphans), status='pending',
    ).update(
        set__status='rejected',
        set__decided_at=datetime.datetime.utcnow(),
        set__decision_reason='Host was deleted',
    )


def _purge_dangling_relations():
    """
    Drop relation edges that point at a host which no longer exists.

    ``HostRelation.target_host`` sits inside an embedded document, where
    MongoEngine cannot attach a delete rule, so versions before the
    queryset-level cleanup left a dangling reference behind on every host
    that pointed at a deleted one. Reading such an edge raises
    ``DoesNotExist``, which used to take the whole host detail view down.

    Returns the number of hosts whose relation list was repaired.
    """
    # Read the raw documents: going through MongoEngine would dereference
    # every edge, which is both the expensive way to collect ObjectIds and
    # the thing that raises on exactly the edges this sweep is looking for.
    collection = Host._get_collection()  # pylint: disable=protected-access
    targets = set()
    for doc in collection.find({'relations': {'$exists': True, '$ne': []}},
                               {'relations.target_host': 1}):
        for rel in doc.get('relations') or []:
            if rel.get('target_host'):
                targets.add(rel['target_host'])
    if not targets:
        return 0
    alive = set(Host.objects(id__in=list(targets)).distinct('id'))
    dangling = targets - alive
    if not dangling:
        return 0
    print(f"{CC.UNDERLINE}Remove relations pointing at deleted hosts{CC.ENDC}")
    print(f"{CC.WARNING}  ** {CC.ENDC}{len(dangling)} deleted target(s) "
          f"still referenced")
    return Host.objects(
        __raw__={'relations.target_host': {'$in': list(dangling)}},
    ).update(
        __raw__={'$pull': {'relations': {
            'target_host': {'$in': list(dangling)}}}},
    )


def _log_maintenance_run(account, details, params):
    """
    Write the maintenance log entry.

    Only the account name belongs in the title — `account` is the full
    account dict in non-legacy mode, and dumping it made the log list
    unreadable. Its parameters are shown in the details table instead.
    """
    title = "Database Maintenance"
    if isinstance(account, dict):
        name = account.get('name', '')
        title = f"{title} ({name})"
        details.append(('account', name))
    details.extend(params.items())
    log.log(title, source="Maintenance", details=details)


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

    purge_days = _resolve_purge_days(account)

    if not days:
        print(f"{CC.WARNING} Days set to 0, skipping archiving step {CC.ENDC}")
    else:
        details.append(('hosts_archived', _archive_unseen_hosts(
            days, account_filter, account_filter_name,
            dont_delete_if_more, details)))

    purged_hosts = _purge_archived_hosts(account_filter, purge_days)
    details.append(('hosts_purged', purged_hosts))

    orphaned_trees = _purge_orphaned_inventory_trees()
    details.append(('inventory_trees_removed', orphaned_trees))

    details.append(('field_approvals_closed', _purge_orphaned_field_approvals()))
    details.append(('dangling_relations_removed', _purge_dangling_relations()))

    _log_maintenance_run(account, details, {
        'delete_hosts_after_days': days,
        'account_filter': account_filter_name or '',
        'dont_delete_hosts_if_more_then': dont_delete_if_more or '',
        'purge_hosts_after_days': purge_days,
    })

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
@click.option('--hostname', default="",
              help="Limit to this host instead of the whole database.")
@click.option('--debug', is_flag=True)
def delete_inventory(prefix_only, hostname, debug):  # pylint: disable=unused-argument
    """
    Delete the inventory of all hosts

    Add a prefix als parameter to limit to only the ones starting with that.
    Use --hostname to clean a single host instead of every host.
    """
    print(f"{CC.HEADER} ***** Delete Inventory ***** {CC.ENDC}")
    db_hosts = Host.objects(hostname=hostname) if hostname else Host.objects()
    if hostname and not db_hosts:
        print(f"{CC.FAIL}  ** {CC.ENDC}Host {hostname} not found")
        return
    for host in db_hosts:
        logger.debug("Handling Host %s", host.hostname)
        if prefix_only:
            prefix = prefix_only.lower()
            new_inventory = {k: v for k, v in host.inventory.items()
                             if not k.lower().startswith(prefix)}
        else:
            new_inventory = {}
        # Inventory values feed the rendered export attributes, so the
        # cache computed from them has to go with them — otherwise the
        # next export still ships the values that were just deleted.
        host.update(set__inventory=new_inventory, set__cache={})
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
#   .-- Command: Delete Empty Labels

def _label_is_empty(value):
    """
    A label counts as empty when it carries no usable value: None, an
    empty/whitespace-only string, or an empty container.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ''
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) == 0
    return False


def _persist_labels(host, new_labels):
    """
    Write a cleaned label set back to the host without running the
    import side effects. Labels feed the attribute cache, so drop it too.
    """
    host.update(set__labels=new_labels, set__cache={})


@_cli_sys.command('delete_empty_labels')
@click.option('--apply', 'do_apply', is_flag=True,
              help="Actually delete. Without this flag it is a dry run.")
@click.option('--debug', is_flag=True)
def delete_empty_labels(do_apply, debug):  # pylint: disable=unused-argument
    """
    Delete labels with an empty value from all hosts.

    Cleans up hosts whose labels carry no value (None, empty string or
    empty container). Runs as a dry run by default and only reports what
    it would remove; pass --apply to write the changes.
    """
    mode = "APPLY" if do_apply else "DRY-RUN"
    print(f"{CC.HEADER} ***** Delete Empty Labels ({mode}) ***** {CC.ENDC}")
    hosts_changed = 0
    labels_removed = 0
    for host in Host.objects(object_type__ne='template'):
        empty_keys = [key for key, value in (host.labels or {}).items()
                      if _label_is_empty(value)]
        if not empty_keys:
            continue
        hosts_changed += 1
        labels_removed += len(empty_keys)
        for key in empty_keys:
            print(f"{CC.WARNING}  ** {CC.ENDC}{host.hostname}: "
                  f"remove '{key}' (empty value: {host.labels[key]!r})")
        if do_apply:
            new_labels = {key: value for key, value in host.labels.items()
                          if key not in empty_keys}
            _persist_labels(host, new_labels)
    verb = "Removed" if do_apply else "Would remove"
    print(f"{CC.OKGREEN}  ** {CC.ENDC}{verb} {labels_removed} label(s) "
          f"on {hosts_changed} host(s)")
    if not do_apply and labels_removed:
        print(f"{CC.OKCYAN}  ** {CC.ENDC}Re-run with --apply to delete them")

#.
#   .-- Command: Delete Template Labels

def _first_template_value(templates, key):
    """
    Return (found, value) for the first assigned template (in order) that
    provides `key`. That first template is the one whose value the host
    would fall back to once its own label is removed.
    """
    for template in templates:
        labels = template.labels or {}
        if key in labels:
            return True, labels[key]
    return False, None


@_cli_sys.command('delete_template_labels')
@click.option('--apply', 'do_apply', is_flag=True,
              help="Actually delete. Without this flag it is a dry run.")
@click.option('--debug', is_flag=True)
def delete_template_labels(do_apply, debug):  # pylint: disable=unused-argument
    """
    Delete host labels that duplicate an assigned CMDB template label.

    A host label is redundant when an assigned template provides the same
    key with the same value: the template supplies it virtually anyway, so
    the host copy is noise. Only removed when the first template providing
    the key holds a plain (non-Jinja) value equal to the host's — so the
    effective attribute never changes. Dry run by default; --apply writes.
    """
    mode = "APPLY" if do_apply else "DRY-RUN"
    print(f"{CC.HEADER} ***** Delete Redundant Template Labels ({mode}) ***** {CC.ENDC}")
    hosts_changed = 0
    labels_removed = 0
    for host in Host.objects(object_type__ne='template', cmdb_templates__ne=[]):
        templates = list(host.cmdb_templates or [])
        if not templates or not host.labels:
            continue
        redundant_keys = []
        for key, value in host.labels.items():
            found, tmpl_value = _first_template_value(templates, key)
            if not found:
                continue
            # Skip Jinja values — their rendered result may differ from the
            # host value, so removing the host label would change attributes.
            if isinstance(tmpl_value, str) and '{{' in tmpl_value:
                continue
            if tmpl_value == value:
                redundant_keys.append(key)
        if not redundant_keys:
            continue
        hosts_changed += 1
        labels_removed += len(redundant_keys)
        for key in redundant_keys:
            print(f"{CC.WARNING}  ** {CC.ENDC}{host.hostname}: "
                  f"remove '{key}={host.labels[key]!r}' "
                  f"(already provided by an assigned template)")
        if do_apply:
            new_labels = {key: value for key, value in host.labels.items()
                          if key not in redundant_keys}
            _persist_labels(host, new_labels)
    verb = "Removed" if do_apply else "Would remove"
    print(f"{CC.OKGREEN}  ** {CC.ENDC}{verb} {labels_removed} label(s) "
          f"on {hosts_changed} host(s)")
    if not do_apply and labels_removed:
        print(f"{CC.OKCYAN}  ** {CC.ENDC}Re-run with --apply to delete them")

#.
#   .-- Command: Lowercase Hostnames
@_cli_sys.command('lowercase_hostnames')
@click.option('--apply', 'do_apply', is_flag=True,
              help="Actually rename. Without this flag it is a dry run.")
@click.option('--debug', is_flag=True)
def lowercase_hostnames(do_apply, debug):  # pylint: disable=unused-argument
    """
    Rename hosts that have uppercase letters in their name to lowercase.

    Dry run by default; pass --apply to write the renames. A host is skipped
    when its lowercase name is already taken by another host.
    """
    # pylint: disable=import-outside-toplevel
    from application.helpers.host_maintenance import lowercase_all_hostnames
    mode = "APPLY" if do_apply else "DRY-RUN"
    print(f"{CC.HEADER} ***** Lowercase Hostnames ({mode}) ***** {CC.ENDC}")
    result = lowercase_all_hostnames(apply=do_apply)
    verb = "Renamed" if do_apply else "Would rename"
    for pair in result['renamed']:
        archived = " [archived]" if pair['archived'] else ""
        print(f"{CC.OKGREEN}  ** {CC.ENDC}{verb} {pair['old']}{archived} "
              f"-> {pair['new']}")
    for pair in result['collisions']:
        archived = " [archived]" if pair['archived'] else ""
        holder = "archived host" if pair['target_archived'] else "host"
        print(f"{CC.WARNING}  ** {CC.ENDC}Skipped {pair['old']}{archived}: "
              f"'{pair['target']}' already exists as {holder} (merge by hand)")
    print(f"{CC.OKGREEN}  ** {CC.ENDC}{verb} {len(result['renamed'])} host(s); "
          f"{len(result['collisions'])} collision(s); "
          f"{result['archived']} of the affected host(s) are archived")
    if not do_apply and result['renamed']:
        print(f"{CC.OKCYAN}  ** {CC.ENDC}Re-run with --apply to rename them")

#.
#   .-- Command: Delete all Hosts
@_cli_sys.command('delete_all_hosts')
@click.argument("account", default="")
@click.option('--include-protected', is_flag=True,
              help="Also delete hosts marked as 'no autodelete'.")
def delete_all_hosts(account, include_protected):
    """
    Deletes All hosts from DB

    Hosts protected against automatic deletion are kept unless
    --include-protected is given. Templates are never deleted.
    """
    print(f"{CC.HEADER} ***** Delete Hosts ***** {CC.ENDC}")
    protected = "deleted too" if include_protected else "kept"
    answer = input(f" - Enter 'y' and hit enter to procceed (Account Filter: "
                   f"{account}, 'no autodelete' hosts are {protected}): ")
    if answer.lower() in ['y', 'z']:
        db_filter = {'object_type__ne': "template"}
        raw_match = {
            "object_type": {"$ne": "template"},
        }
        if not include_protected:
            db_filter['no_autodelete__ne'] = True
            raw_match['no_autodelete'] = {"$ne": True}
        print(f"{CC.WARNING}  ** {CC.ENDC}Start deletion")

        if account:
            db_filter['source_account_name'] = account
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
                # Only pool folders keep a seat count; a host can sit in
                # any folder, so a folder without a pool is nothing to
                # give seats back to.
                folder = CheckmkFolderPool.objects(
                    folder_name__iexact=folder_name).first()
                if not folder:
                    continue
                if folder.folder_seats_taken > count:
                    folder.folder_seats_taken -= count
                else:
                    folder.folder_seats_taken = 0
                folder.save()
        Host.objects(**db_filter).delete()
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


def _migrate_project_collection():
    """
    Move documents from the legacy ``checkmk_rule_project`` collection into
    the generic ``project`` collection (the CheckmkRuleProject model became
    the plain Project model). Idempotent: existing targets (matched by name)
    are never overwritten, and the legacy collection is dropped once every
    document has been carried over.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.project import Project
    print("Check for legacy checkmk_rule_project collection")
    database = Project._get_collection().database  # pylint: disable=protected-access
    if 'checkmk_rule_project' not in database.list_collection_names():
        print(" -> Nothing to migrate")
        return
    legacy = database['checkmk_rule_project']
    target = database['project']
    moved = 0
    for doc in legacy.find():
        if target.find_one({'name': doc.get('name')}):
            continue
        target.insert_one(doc)
        moved += 1
    legacy.drop()
    print(f" -> Migrated {moved} project(s), removed legacy collection")


def _warn_migrated_account_settings(config):
    """
    Warn loudly if the deprecated CHECK_FOR_VALID_HOSTNAME / REQUIRE_FQDN
    keys are still present in local_config.py. Both moved to the Account
    (Object Settings) and have no effect from local_config.py any more.
    """
    migrated = [key for key in ('CHECK_FOR_VALID_HOSTNAME', 'REQUIRE_FQDN')
                if key in config]
    if not migrated:
        return
    line = "!" * 72
    print(f"\n{CC.FAIL}{line}")
    print("!! ACTION REQUIRED: deprecated hostname-check settings found")
    print(f"{line}{CC.ENDC}")
    for key in migrated:
        print(f"{CC.FAIL}  * {key} = {config[key]!r}{CC.ENDC}")
    print(f"{CC.WARNING}These settings moved to the Account (Object "
          "Settings): 'Check for valid hostname' and 'Require FQDN'. They "
          "no longer take effect from local_config.py and, unlike before, "
          "no longer apply to object accounts.")
    print("Enable them on the accounts that need them, then remove the "
          f"keys above from local_config.py.{CC.ENDC}")
    print(f"{CC.FAIL}{line}{CC.ENDC}\n")


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
    _warn_migrated_account_settings(config)
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

    # Rule Projects became generic Projects
    _migrate_project_collection()

    # Keep every TTL in sync with its configured retention. MongoEngine
    # only creates those indexes, it never updates their
    # expireAfterSeconds, so an edited retention takes effect here.
    print("Sync retention of the collections that grow with every run")
    for name, days, action in sync_all():
        print(f" -> {name}: TTL index {action} ({days} days)")

    print("Drop indexes the models no longer declare")
    for dropped in drop_stale_indexes():
        print(f" -> dropped {dropped}")

    # Recount Checkmk pool seat usage so the counters are correct after an update
    # pylint: disable=import-outside-toplevel
    from application.plugins.checkmk.inits import sync_folderpools, sync_sitepools
    print("Sync Checkmk Folder Pools")
    sync_folderpools()
    print("Sync Checkmk Site Pools")
    sync_sitepools()

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

# Database housekeeping commands live in their own module — they attach
# to `_cli_sys` above, so they can only be imported once it exists.
from application.plugins.maintenance import db_commands  # noqa: E402,F401  pylint: disable=wrong-import-position,unused-import
