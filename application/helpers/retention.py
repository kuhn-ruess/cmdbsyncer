"""
TTL retention for the collections that grow with every run.

Every collection that gets one document per run, per host or per
decision needs an upper bound, or it eventually becomes the database.
The bound is a TTL index: MongoDB drops the expired documents itself,
so there is no cron job that can be forgotten and no cleanup that only
runs when someone remembers it.

A model registers its policy next to its index definition via
`register_retention`. `sys self_configure` walks the registry and makes
every TTL match its configured number of days — necessary because
MongoEngine only ever *creates* an index and silently ignores a changed
`expireAfterSeconds` on an existing one.
"""
from application import app

# Registered policies, in registration order:
# (name, document_class, field, config_key, default_days)
_POLICIES = []


def register_retention(name, document_class, field, config_key, default_days):
    """
    Declare that `field` of `document_class` expires after the number of
    days configured under `config_key`. Called from the model module so
    the policy sits next to the index it belongs to. Idempotent — a
    re-registered name replaces the earlier entry.
    """
    entry = (name, document_class, field, config_key, default_days)
    for index, existing in enumerate(_POLICIES):
        if existing[0] == name:
            _POLICIES[index] = entry
            return
    _POLICIES.append(entry)


def retention_days(config_key, default_days):
    """
    Configured retention in days, never below one. Zero would reach
    MongoDB as "expire at the timestamp itself", which deletes the
    documents as they are written — not what anyone means by 0.
    """
    try:
        days = int(app.config.get(config_key, default_days))
    except (TypeError, ValueError):
        days = default_days
    return max(days, 1)


def retention_seconds(config_key, default_days):
    """Configured retention as the `expireAfterSeconds` an index wants."""
    return retention_days(config_key, default_days) * 86400


def sync_ttl_index(document_class, field, seconds):
    """
    Make the TTL index on `field` match `seconds`, creating it when it
    is missing and applying a changed retention with collMod.

    Returns 'created', 'updated' or 'unchanged'.
    """
    collection = document_class._get_collection()  # pylint: disable=protected-access
    for name, index in collection.index_information().items():
        if index.get('key') != [(field, 1)]:
            continue
        if index.get('expireAfterSeconds') == seconds:
            return 'unchanged'
        collection.database.command(
            'collMod', collection.name,
            index={'name': name, 'expireAfterSeconds': seconds},
        )
        return 'updated'
    collection.create_index(field, expireAfterSeconds=seconds)
    return 'created'


# Model modules that register a policy but are not imported by every
# entry point — the label history is imported lazily from Host.save(),
# the approval queue only by the web layer. Without this the CLI would
# quietly sync a subset. Plugin and Enterprise models are imported by
# their own package on startup and register themselves.
_POLICY_MODULES = (
    'application.models.host_label_event',
    'application.models.field_approval',
)


def _import_policy_models():
    """Import the model modules whose policies would otherwise be missing."""
    for module in _POLICY_MODULES:
        __import__(module)


def sync_all():
    """
    Apply every registered policy. Yields (name, days, action) so the
    caller can report what changed.
    """
    _import_policy_models()
    for name, document_class, field, config_key, default_days in _POLICIES:
        days = retention_days(config_key, default_days)
        action = sync_ttl_index(document_class, field, days * 86400)
        yield name, days, action
