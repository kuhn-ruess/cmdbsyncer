"""
Lookup Tables for Jinja

``lookup(table, key)`` answers "attribute A has value x, which value does
attribute B get?" from a table maintained in the UI (Modules > Lookup
Tables) instead of one rule per value.
"""
# pylint: disable=import-outside-toplevel
import time

import jinja2

from application.modules.rule.list_source import parse_list_source

# A lookup table is meant for long lists, so it allows more rows than a
# rule's pasted list does.
MAX_ROWS = 100000

# How long a process keeps a table before it reads it again. An export
# asks the same table once per host, a saved change still arrives within
# this time in a process that is already running (web workers).
CACHE_SECONDS = 60

_CACHE = {}


MODE_KEY_VALUE = 'key_value'
MODE_TABLE = 'table'
MODES = [
    (MODE_KEY_VALUE, 'Key / Value'),
    (MODE_TABLE, 'Table'),
]


def parse_lookup_table(text, mode=MODE_KEY_VALUE):
    """
    Parse the text of a lookup table into ``(columns, rows, errors)``.

    ``rows`` is one dict (column name to cell) per line, in the order of
    the table. In Key / Value mode the first column is a key: it needs a
    value column beside it, and a key that appears twice is an error,
    which of the rows would win is not obvious to whoever maintains the
    list. A Table takes any number of columns and repeated values.
    """
    parsed = parse_list_source(text, max_rows=MAX_ROWS)
    errors = list(parsed.errors)
    if mode == MODE_TABLE:
        return parsed.columns, parsed.rows, errors
    if parsed.columns and len(parsed.columns) < 2:
        errors.append("The table needs at least two columns: the key and a value. "
                      "Use the mode Table for a list of one column")
    seen = set()
    duplicates = []
    if parsed.columns:
        key_column = parsed.columns[0]
        for row in parsed.rows:
            key = row[key_column]
            if key in seen and key not in duplicates:
                duplicates.append(key)
            seen.add(key)
    if duplicates:
        shown = ', '.join(f"'{key}'" for key in duplicates[:10])
        more = f" and {len(duplicates) - 10} more" if len(duplicates) > 10 else ""
        errors.append(f"Keys used more than once: {shown}{more}")
    return parsed.columns, parsed.rows, errors


def _load_table(name):
    """
    The parsed table of the given name: ``(columns, rows, index)``, or
    None when there is no such table. ``index`` maps the value of the
    first column to the first row that has it.
    """
    from application.models.lookup_table import LookupTable
    entry = LookupTable.objects(name=name).only('mode', 'entries').first()
    if entry is None:
        return None
    columns, rows, _errors = parse_lookup_table(entry.entries, entry.mode)
    index = {}
    if columns:
        for row in rows:
            index.setdefault(row[columns[0]], row)
    return columns, rows, index


def _get_table(name):
    """``_load_table`` through the per process cache."""
    now = time.monotonic()
    cached = _CACHE.get(name)
    if cached is not None and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    loaded = _load_table(name)
    _CACHE[name] = (now, loaded)
    return loaded


def clear_cache():
    """Forget every cached table, e.g. after one was saved."""
    _CACHE.clear()


def lookup(table, key, column=None, default=''):
    """
    The value the lookup table ``table`` has for ``key``.

    ``key`` is compared with the first column of the table. ``column``
    names the column to return (its variable name, as for a pasted list),
    without it the second column is returned. In a Table the first line
    with that key counts. An unknown table, key or column, or an empty
    cell, gives ``default``.
    """
    if key is None or isinstance(key, jinja2.Undefined):
        return default
    loaded = _get_table(table)
    if not loaded:
        return default
    columns, _rows, index = loaded
    row = index.get(str(key).strip())
    if row is None:
        return default
    if column is None:
        column = columns[1] if len(columns) > 1 else None
    return row.get(column) or default


def lookup_keys(table):
    """
    The values in the first column of the lookup table ``table`` as a
    set, or None when there is no such table.
    """
    loaded = _get_table(table)
    if not loaded:
        return None
    _columns, _rows, index = loaded
    return set(index)


def lookup_rows(table):
    """
    Every row of the lookup table ``table``, in the order of the table,
    as a dict of column name to cell. An unknown table gives an empty list.
    """
    loaded = _get_table(table)
    if not loaded:
        return []
    _columns, rows, _index = loaded
    # Copies, so a template cannot change the cached table.
    return [dict(row) for row in rows]
