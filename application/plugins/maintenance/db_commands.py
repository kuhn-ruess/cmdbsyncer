"""
Database housekeeping commands of the `sys` CLI group.

Registered on the group from `application/plugins/maintenance/__init__.py`,
which imports this module once that group exists.
"""
import click

from application.modules.debug import ColorCodes as CC
from application.helpers.db_analysis import (
    GROWING_COLLECTIONS,
    database_stats,
    format_size,
    largest_documents,
)
from application.helpers.label_history import (
    analyze_collection,
    collection_count,
    count_expired,
    cutoff_for,
    drop_collection,
    has_changed_at_index,
    history_collections,
    label_history_enabled,
    label_history_retention_days,
    purge_expired,
)
from application.plugins.maintenance import _cli_sys


#   .-- Command: Database Statistics

def _print_totals(stats):
    """Print the database wide numbers above the collection table."""
    print(f"Database: {stats['database']}")
    print(f"  Documents    : {stats['objects']:,}")
    print(f"  Data size    : {format_size(stats['data_size'])} (uncompressed)")
    print(f"  Storage size : {format_size(stats['storage_size'])} (on disk)")
    print(f"  Index size   : {format_size(stats['index_size'])}")
    print(f"  Total on disk: "
          f"{format_size(stats['storage_size'] + stats['index_size'])}")
    print(f"  Reusable     : {format_size(stats['free_size'])} "
          f"(freed by deletes, given back to the filesystem by compact)")
    if stats['fs_total_size']:
        print(f"  Filesystem   : {format_size(stats['fs_used_size'])} used of "
              f"{format_size(stats['fs_total_size'])}")


def _print_collections(collections, grand_total, show_indexes):
    """
    Print one line per collection, biggest first. The share is always
    relative to the whole database, not to the listed subset.
    """
    grand_total = grand_total or 1
    print(f"\n{'Collection':<34}{'Documents':>12}{'Data':>11}"
          f"{'Storage':>11}{'Indexes':>11}{'Total':>11}{'%':>7}")
    print("-" * 97)
    for entry in collections:
        share = entry['total'] / grand_total * 100
        print(f"{entry['name']:<34}{entry['count']:>12,}"
              f"{format_size(entry['data_size']):>11}"
              f"{format_size(entry['storage_size']):>11}"
              f"{format_size(entry['index_size']):>11}"
              f"{format_size(entry['total']):>11}{share:>6.1f}%")
        if show_indexes:
            for index_name, size in sorted(entry['index_sizes'].items(),
                                           key=lambda x: x[1], reverse=True):
                print(f"    {CC.OKCYAN}index{CC.ENDC} {index_name:<28}"
                      f"{format_size(size):>11}")


def _print_growth_hints(collections):
    """Point out the listed collections that have no automatic cleanup."""
    hints = [x for x in collections if x['name'] in GROWING_COLLECTIONS]
    if not hints:
        return
    print(f"\n{CC.UNDERLINE}Collections that grow with every run{CC.ENDC}")
    for entry in hints:
        print(f"{CC.WARNING}  ** {CC.ENDC}{entry['name']} "
              f"({format_size(entry['total'])}, {entry['count']:,} documents): "
              f"{GROWING_COLLECTIONS[entry['name']]}")


def _print_largest_documents(collection):
    """Print the biggest documents of a single collection."""
    print(f"\n{CC.UNDERLINE}Largest documents in {collection}{CC.ENDC}")
    entries = largest_documents(collection)
    if not entries:
        print(f"{CC.WARNING}  ** {CC.ENDC}No documents (unknown collection?)")
        return
    for entry in entries:
        print(f"{CC.OKCYAN}  ** {CC.ENDC}{format_size(entry['size']):>10}  "
              f"{entry['label']} ({entry['id']})")


@_cli_sys.command('db_stats')
@click.option('--top', default=15, show_default=True,
              help="How many collections to list. 0 lists all of them.")
@click.option('--indexes', 'show_indexes', is_flag=True,
              help="Also list every index with its size.")
@click.option('--collection', default='',
              help="Drill down: also show the largest documents of "
                   "COLLECTION (scans it).")
@click.option('--debug', is_flag=True)
def db_stats(top, show_indexes, collection, debug):  # pylint: disable=unused-argument
    """
    Show what occupies the space in MongoDB.

    Lists the database totals and every collection with its document
    count, data size, size on disk and index size, biggest first, so a
    database that ran full shows its cause at a glance.
    """
    print(f"{CC.HEADER} ***** MongoDB Storage Analysis ***** {CC.ENDC}")
    stats = database_stats()
    _print_totals(stats)
    listed = stats['collections'] if not top else stats['collections'][:top]
    grand_total = sum(x['total'] for x in stats['collections'])
    _print_collections(listed, grand_total, show_indexes)
    hidden = len(stats['collections']) - len(listed)
    if hidden > 0:
        print(f"{CC.OKCYAN}  ** {CC.ENDC}{hidden} smaller collection(s) not "
              f"shown, use --top 0 for all")
    _print_growth_hints(listed)
    if collection:
        _print_largest_documents(collection)

#.
#   .-- Command: Label History

def _print_history_analysis(report):
    """Print where the entries of one history collection come from."""
    name = report['collection']
    if not report['total']:
        print(f"\n{CC.OKGREEN}  ** {CC.ENDC}{name}: empty")
        return
    print(f"\n{CC.UNDERLINE}{name}{CC.ENDC}")
    print(f"  entries : {report['total']:,}")
    print(f"  period  : {report['oldest']} .. {report['newest']}")
    print(f"  sample  : {report['sample_size']:,} entries")
    print(f"  {'top label keys':<40}{'share of sample':>16}")
    for key, count in report['top_keys']:
        share = count / report['sample_size'] * 100
        print(f"  {key[:40]:<40}{count:>9,} {share:>5.1f}%")
    print(f"  {'top hosts':<40}{'share of sample':>16}")
    for hostname, count in report['top_hosts']:
        share = count / report['sample_size'] * 100
        print(f"  {hostname[:40]:<40}{count:>9,} {share:>5.1f}%")


@_cli_sys.command('label_history')
@click.option('--sample', default=100000, show_default=True,
              help="How many entries to sample for the breakdown.")
@click.option('--debug', is_flag=True)
def label_history(sample, debug):  # pylint: disable=unused-argument
    """
    Show what the host label history costs and what fills it.

    Lists every history collection with its size and period, and breaks
    a random sample down by label key and host — the key at the top is
    the one an import rewrites on every run.
    """
    print(f"{CC.HEADER} ***** Label History ***** {CC.ENDC}")
    enabled = label_history_enabled()
    state = "on" if enabled else "off"
    print(f"Recording: {state} (LABEL_HISTORY_ENABLED), "
          f"retention {label_history_retention_days()} days")
    names = history_collections()
    if not names:
        print(f"{CC.OKGREEN}  ** {CC.ENDC}No label history in this database")
        return
    for name in names:
        _print_history_analysis(analyze_collection(name, sample_size=sample))
    print(f"\n{CC.OKCYAN}  ** {CC.ENDC}Clean up with "
          f"'cmdbsyncer sys purge_label_history'")

#.
#   .-- Command: Purge Label History

def _purge_one(name, cutoff, do_apply):
    """Delete the expired entries of one collection, with progress."""
    if not has_changed_at_index(name):
        print(f"{CC.WARNING}  ** {CC.ENDC}{name}: no index on changed_at, "
              f"counting and deleting by age reads the whole collection. "
              f"On a large one use --all to drop it instead.")
    expired = count_expired(name, cutoff)
    if not expired:
        print(f"{CC.OKGREEN}  ** {CC.ENDC}{name}: nothing older than the cutoff")
        return 0
    if not do_apply:
        print(f"{CC.WARNING}  ** {CC.ENDC}{name}: would delete "
              f"{expired:,} entries")
        return expired
    print(f"{CC.WARNING}  ** {CC.ENDC}{name}: deleting {expired:,} entries")
    deleted = 0
    for deleted in purge_expired(name, cutoff):
        print(f"      {deleted:,} / {expired:,}", end='\r', flush=True)
    print(f"\n{CC.OKGREEN}  ** {CC.ENDC}{name}: deleted {deleted:,} entries")
    return deleted


@_cli_sys.command('purge_label_history')
@click.option('--days', default=None, type=int,
              help="Delete entries older than DAYS. Defaults to the "
                   "configured LABEL_HISTORY_RETENTION_DAYS.")
@click.option('--all', 'drop_all', is_flag=True,
              help="Drop the history collections completely. Frees the "
                   "disk space right away, unlike a delete.")
@click.option('--collection', default='',
              help="Limit to one history collection instead of all of "
                   "them, e.g. the legacy 'host_label_change'.")
@click.option('--apply', 'do_apply', is_flag=True,
              help="Actually delete. Without this flag it is a dry run.")
@click.option('--debug', is_flag=True)
def purge_label_history(days, drop_all, collection, do_apply, debug):  # pylint: disable=unused-argument
    """
    Clean up the host label history.

    Removes entries older than the retention from every history
    collection, including the legacy one written by earlier versions;
    --collection limits that to a single one. With --all the collections
    are dropped instead, which is the only way to get the disk space
    back immediately.

    Dry run by default; pass --apply to write.
    """
    mode = "APPLY" if do_apply else "DRY-RUN"
    print(f"{CC.HEADER} ***** Purge Label History ({mode}) ***** {CC.ENDC}")
    names = history_collections()
    if collection:
        names = [name for name in names if name == collection]
        if not names:
            print(f"{CC.FAIL}  ** {CC.ENDC}No history collection named "
                  f"'{collection}' in this database")
            return
    if not names:
        print(f"{CC.OKGREEN}  ** {CC.ENDC}No label history in this database")
        return
    print(f"Collections: {', '.join(names)}")

    if drop_all:
        for name in names:
            if not do_apply:
                print(f"{CC.WARNING}  ** {CC.ENDC}{name}: would be dropped "
                      f"with all {collection_count(name):,} entries")
                continue
            drop_collection(name)
            print(f"{CC.OKGREEN}  ** {CC.ENDC}{name}: dropped")
    else:
        cutoff = cutoff_for(days if days is not None
                            else label_history_retention_days())
        print(f"Cutoff: entries changed before {cutoff}")
        for name in names:
            _purge_one(name, cutoff, do_apply)

    if not do_apply:
        print(f"{CC.OKCYAN}  ** {CC.ENDC}Re-run with --apply to delete")
        return
    print(f"{CC.OKCYAN}  ** {CC.ENDC}Deleted space stays reserved by MongoDB "
          f"until the collection is compacted "
          f"(db.runCommand({{compact: '<collection>'}}))")
