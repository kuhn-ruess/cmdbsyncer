"""
Validate dictionary keys before they are handed to MongoDB.

MongoDB rejects field names that are empty, `$`-prefixed, or contain `.`.
Validating at the point of write — from API handlers, plugins, and
importers alike — raises ValueError with a clear message instead of
leaking a driver-level 500 mid-save.
"""


def validate_mongo_key(key, what):
    """Raise ValueError if `key` cannot be stored as a MongoDB field name."""
    if not isinstance(key, str) or not key:
        raise ValueError(f"{what} key must be a non-empty string")
    if key.startswith('$') or '.' in key:
        raise ValueError(
            f"{what} key '{key}' must not start with '$' or contain '.'"
        )


def validate_mongo_keys(mapping, what):
    """Raise ValueError if any of `mapping`'s keys cannot be stored."""
    if not isinstance(mapping, dict):
        return
    for key in mapping:
        validate_mongo_key(key, what)
