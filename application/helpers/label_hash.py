"""
Stable short hashes for attribute values.

Kept free of any import beyond the standard library so every layer can
use it — the Jinja environment, the Checkmk rule analysis and the tests
alike.
"""
import hashlib


def syncer_hash(value, length=8):
    """
    Short, stable hex digest of a value.

    Turns something that cannot be a Checkmk label — a comma-separated
    list, a value with spaces, a service pattern — into one that can,
    while staying identical for identical input. That makes it usable as
    a rule condition: hosts sharing the value share the hash.

    A container is sorted before hashing (a set has no order at all, and
    for grouping the order of a list carries no meaning). Everything else
    is hashed as its stripped string form.

    Deliberately sha256 and not Python's ``hash()``: the builtin is
    salted per process, so it would produce a different label on every
    run.
    """
    if isinstance(value, (list, tuple, set)):
        text = ",".join(sorted(str(entry).strip() for entry in value))
    else:
        text = str(value if value is not None else '').strip()
    try:
        length = int(length)
    except (TypeError, ValueError):
        length = 8
    length = max(4, min(length, 64))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:length]
