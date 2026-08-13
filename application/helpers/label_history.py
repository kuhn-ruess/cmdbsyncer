"""
Settings, retention and cleanup for the host label history (Timeline
tab).

Recording label changes is optional and bounded: it only happens when
LABEL_HISTORY_ENABLED is set, and MongoDB drops events older than
LABEL_HISTORY_RETENTION_DAYS through a TTL index. Both live in
local_config.py and can be edited from the Config UI.

This module also carries the tooling for installations that ran with
the earlier, unbounded design: an analysis of what the history costs
and where the churn comes from, plus the cleanup that gets the space
back.
"""
import datetime
from mongoengine import get_db
from application import app

DEFAULT_RETENTION_DAYS = 90

# Name of the legacy per-label collection (one document per changed
# label). Superseded by the per-event `host_label_event` collection;
# `sys purge_label_history` removes whatever is left of it.
LEGACY_COLLECTION = 'host_label_change'


def label_history_enabled():
    """True when hosts should record their label changes."""
    return bool(app.config.get('LABEL_HISTORY_ENABLED', False))


def label_history_retention_days():
    """
    Days an entry of the label history is kept. Always at least one day
    — "keep forever" is what filled databases in the first place, so it
    is deliberately not offered.
    """
    try:
        days = int(app.config.get('LABEL_HISTORY_RETENTION_DAYS',
                                  DEFAULT_RETENTION_DAYS))
    except (TypeError, ValueError):
        days = DEFAULT_RETENTION_DAYS
    return max(days, 1)


def label_history_retention_seconds():
    """Retention as the `expireAfterSeconds` a TTL index expects."""
    return label_history_retention_days() * 86400


def sync_label_history_ttl():
    """
    Make the TTL index on the label history match the configured
    retention.

    MongoEngine only ever *creates* indexes — a changed
    `expireAfterSeconds` on an existing index is silently ignored, so
    editing the retention would never take effect. Applied with collMod
    instead.

    Returns (seconds, action) where action is one of 'created',
    'updated' or 'unchanged'.
    """
    # pylint: disable=import-outside-toplevel,protected-access
    from application.models.host_label_event import HostLabelEvent
    collection = HostLabelEvent._get_collection()
    wanted = label_history_retention_seconds()
    for name, index in collection.index_information().items():
        if index.get('key') != [('changed_at', 1)]:
            continue
        if index.get('expireAfterSeconds') == wanted:
            return wanted, 'unchanged'
        collection.database.command(
            'collMod', collection.name,
            index={'name': name, 'expireAfterSeconds': wanted},
        )
        return wanted, 'updated'
    collection.create_index('changed_at', expireAfterSeconds=wanted)
    return wanted, 'created'


def history_collections():
    """The history collections present in this database, newest first."""
    # pylint: disable=import-outside-toplevel,protected-access
    from application.models.host_label_event import HostLabelEvent
    database = get_db()
    existing = set(database.list_collection_names())
    names = [HostLabelEvent._get_collection_name(), LEGACY_COLLECTION]
    return [name for name in names if name in existing]


def _key_pipeline(collection_name):
    """
    Stages that turn one document into one row per changed label key.
    The legacy collection carries the key on the document itself, the
    event collection in its `changes` array.
    """
    if collection_name == LEGACY_COLLECTION:
        return [{'$project': {'key': '$key', 'host': '$host'}}]
    return [
        {'$unwind': '$changes'},
        {'$project': {'key': '$changes.key', 'host': '$host'}},
    ]


def _resolve_hostnames(host_ids):
    """Map host ObjectIds to hostnames; unknown ids keep their id."""
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    names = {}
    for host in Host.objects(id__in=list(host_ids)).only('hostname'):
        names[host.pk] = host.hostname
    return {host_id: names.get(host_id, str(host_id)) for host_id in host_ids}


def analyze_collection(collection_name, sample_size=100000, top=10):
    """
    Where the entries of one history collection come from.

    Groups a random sample by label key and by host, so the label that
    churns on every import — the usual reason this collection grows out
    of proportion — is the top row. Sampling keeps this answerable on a
    collection with hundreds of millions of documents; the counts are
    reported as shares of the sample, not as absolutes.
    """
    database = get_db()
    collection = database[collection_name]
    total = collection.estimated_document_count()
    if not total:
        return {'collection': collection_name, 'total': 0}

    sample_size = min(sample_size, total)
    oldest = collection.find({}, {'changed_at': 1}).sort('changed_at', 1).limit(1)
    newest = collection.find({}, {'changed_at': 1}).sort('changed_at', -1).limit(1)

    def _top(field):
        pipeline = (
            [{'$sample': {'size': sample_size}}]
            + _key_pipeline(collection_name)
            + [{'$group': {'_id': f'${field}', 'count': {'$sum': 1}}},
               {'$sort': {'count': -1}}, {'$limit': top}]
        )
        return list(collection.aggregate(pipeline, allowDiskUse=True))

    top_keys = _top('key')
    top_hosts = _top('host')
    hostnames = _resolve_hostnames([row['_id'] for row in top_hosts])
    return {
        'collection': collection_name,
        'total': total,
        'sample_size': sample_size,
        'oldest': next(iter(oldest), {}).get('changed_at'),
        'newest': next(iter(newest), {}).get('changed_at'),
        'top_keys': [(row['_id'], row['count']) for row in top_keys],
        'top_hosts': [(hostnames[row['_id']], row['count'])
                      for row in top_hosts],
    }


def has_changed_at_index(collection_name):
    """
    True when a date-based purge of this collection is index-backed.
    The legacy collection indexed `changed_at` only behind `host`, so
    deleting by age there scans every document — on a collection with
    hundreds of millions of rows that is hours, and dropping it is the
    better answer.
    """
    for index in get_db()[collection_name].index_information().values():
        if index.get('key', [])[:1] == [('changed_at', 1)]:
            return True
    return False


def count_expired(collection_name, cutoff):
    """How many entries of a collection are older than `cutoff`."""
    return get_db()[collection_name].count_documents(
        {'changed_at': {'$lt': cutoff}})


def purge_expired(collection_name, cutoff, batch_size=50000):
    """
    Delete entries older than `cutoff` in batches, yielding the running
    total after each batch so a caller can show progress. Batched on
    purpose: a single delete over a hundred million documents holds one
    operation open for hours with nothing to look at.
    """
    collection = get_db()[collection_name]
    deleted = 0
    while True:
        ids = [doc['_id'] for doc in collection.find(
            {'changed_at': {'$lt': cutoff}}, {'_id': 1}).limit(batch_size)]
        if not ids:
            return
        deleted += collection.delete_many({'_id': {'$in': ids}}).deleted_count
        yield deleted


def drop_collection(collection_name):
    """
    Drop a history collection outright. Unlike a delete this returns the
    space to the filesystem immediately, which is what an installation
    with a full disk actually needs.
    """
    get_db().drop_collection(collection_name)


def cutoff_for(days):
    """The `changed_at` boundary for a retention of `days` days."""
    return datetime.datetime.utcnow() - datetime.timedelta(days=days)


def collection_count(collection_name):
    """Estimated number of entries in a history collection."""
    return get_db()[collection_name].estimated_document_count()
