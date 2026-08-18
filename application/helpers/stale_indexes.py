"""
Indexes a model used to declare and no longer does.

MongoEngine only ever creates indexes. It never removes one that a model
stopped declaring, so a dropped declaration keeps costing write
throughput and storage on every existing installation — and a stale
*unique* index is worse than that: once the field behind it is gone,
every document indexes as null, and the second insert fails with a
duplicate-key error naming a field the model no longer has.

Models register theirs here and ``cmdbsyncer sys self_configure`` drops
them. Same shape as ``application.helpers.retention``, so plugin and
Enterprise models can register from their own package on import.
"""
from mongoengine import get_db

# (collection_name, index_name), in registration order.
_STALE_INDEXES = []


def register_stale_index(collection_name, index_name):
    """
    Declare that `index_name` on `collection_name` is no longer wanted.
    Idempotent — registering the same pair twice keeps one entry.
    """
    entry = (collection_name, index_name)
    if entry not in _STALE_INDEXES:
        _STALE_INDEXES.append(entry)


def drop_stale_indexes():
    """
    Drop every registered index that still exists. Yields the
    ``collection.index`` names actually dropped, so the caller can report
    them. Safe to run repeatedly.
    """
    database = get_db()
    existing = set(database.list_collection_names())
    for collection_name, index_name in _STALE_INDEXES:
        if collection_name not in existing:
            continue
        collection = database[collection_name]
        if index_name not in collection.index_information():
            continue
        collection.drop_index(index_name)
        yield f'{collection_name}.{index_name}'


# Superseded by the (hostname, source) unique index, whose leftmost prefix
# already serves every query on hostname alone.
register_stale_index('host_inventory_tree', 'hostname_1')
