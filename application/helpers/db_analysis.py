"""
MongoDB storage analysis.

Answers "what is filling up the database" without a Mongo shell: per
collection document count, uncompressed data size, size on disk, index
size and share of the total — plus a drill-down listing the largest
documents of a single collection.

The overview reads the numbers MongoDB keeps itself (`dbStats` /
`$collStats`), so it stays cheap even on a database that has already
run full. The drill-down is the exception: `$bsonSize` is computed per
document and therefore scans the collection.
"""
from mongoengine import get_db
from pymongo.errors import PyMongoError

# Collections that keep growing with every run. Printed as a hint below
# the table so a full database has an obvious first place to look.
GROWING_COLLECTIONS = {
    'log_entry':
        "Run log. Entries expire after 30 days; a huge collection means "
        "very noisy runs or a missing TTL index on 'datetime'.",
    'host_label_change':
        "Label history behind the host Timeline tab. One entry per label "
        "that changes on import — no automatic cleanup.",
    'audit_entry':
        "Audit log. Kept until pruned by hand from the Audit Log view.",
    'ansible_run_stats':
        "One entry per Ansible playbook run, including its full log — no "
        "automatic cleanup.",
    'host_inventory_tree':
        "Full HW/SW inventory trees, current plus previous snapshot, one "
        "document per host and source.",
    'checkmk_object_cache':
        "Cached Checkmk objects. Safe to delete, it is rebuilt on the "
        "next run.",
    'host':
        "The hosts themselves. Check the drill-down: large documents "
        "usually mean big inventory data or long label lists.",
}

# Fields tried, in order, to give a document a recognizable name in the
# drill-down. The first one a collection happens to carry wins.
LABEL_FIELDS = ('hostname', 'name', 'message', 'cache_group', 'key')


def format_size(num_bytes):
    """Byte count as a human readable string."""
    value = float(num_bytes or 0)
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == 'B' else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def _storage_stats(database, name):
    """
    Storage numbers of one collection. Returns None for anything that
    does not report them (views, collections dropped underneath us).
    """
    try:
        result = next(iter(database[name].aggregate(
            [{'$collStats': {'storageStats': {}}}])), None)
    except PyMongoError:
        return None
    if not result:
        return None
    stats = result.get('storageStats', {})
    storage_size = stats.get('storageSize', 0)
    index_size = stats.get('totalIndexSize', 0)
    return {
        'name': name,
        'count': stats.get('count', 0),
        'data_size': stats.get('size', 0),
        'storage_size': storage_size,
        'free_size': stats.get('freeStorageSize', 0),
        'index_size': index_size,
        'index_sizes': dict(stats.get('indexSizes', {})),
        'avg_obj_size': stats.get('avgObjSize', 0),
        'total': storage_size + index_size,
    }


def database_stats():
    """
    Storage picture of the whole database: the server's own totals plus
    one entry per collection, biggest first.
    """
    database = get_db()
    totals = database.command('dbStats')
    collections = []
    for name in database.list_collection_names():
        stats = _storage_stats(database, name)
        if stats:
            collections.append(stats)
    collections.sort(key=lambda entry: entry['total'], reverse=True)
    free_size = totals.get('totalFreeStorageSize')
    if free_size is None:
        free_size = sum(x['free_size'] for x in collections)
    return {
        'database': database.name,
        'objects': totals.get('objects', 0),
        'data_size': totals.get('dataSize', 0),
        'storage_size': totals.get('storageSize', 0),
        'index_size': totals.get('indexSize', 0),
        'free_size': free_size,
        'fs_used_size': totals.get('fsUsedSize'),
        'fs_total_size': totals.get('fsTotalSize'),
        'collections': collections,
    }


def _label_expression():
    """
    Aggregation expression picking the first LABEL_FIELDS entry the
    document carries, falling back to its id. Built as nested $ifNull
    so it also works on older MongoDB releases.
    """
    expression = {'$toString': '$_id'}
    for field in reversed(LABEL_FIELDS):
        expression = {'$ifNull': [f'${field}', expression]}
    return expression


def largest_documents(collection_name, limit=5):
    """
    The `limit` largest documents of a collection, each with its BSON
    size and a name to recognize it by.

    Scans the collection, so this is the opt-in drill-down and not part
    of the overview.
    """
    database = get_db()
    pipeline = [
        {'$project': {'doc_size': {'$bsonSize': '$$ROOT'},
                      'label': _label_expression()}},
        {'$sort': {'doc_size': -1}},
        {'$limit': limit},
    ]
    return [{
        'id': str(entry['_id']),
        'label': str(entry.get('label', '')),
        'size': entry['doc_size'],
    } for entry in database[collection_name].aggregate(pipeline)]
