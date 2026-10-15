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


def parse_lookup_table(text):
    """
    Parse the text of a lookup table into ``(columns, table, errors)``.

    ``table`` maps the value of the first column to its row (column name
    to cell). A key that appears twice is an error: which of the rows
    would win is not obvious to whoever maintains the list.
    """
    parsed = parse_list_source(text, max_rows=MAX_ROWS)
    errors = list(parsed.errors)
    if parsed.columns and len(parsed.columns) < 2:
        errors.append("The table needs at least two columns: the key and a value")
    table = {}
    duplicates = []
    if parsed.columns:
        key_column = parsed.columns[0]
        for row in parsed.rows:
            key = row[key_column]
            if key in table and key not in duplicates:
                duplicates.append(key)
            table[key] = row
    if duplicates:
        shown = ', '.join(f"'{key}'" for key in duplicates[:10])
        more = f" and {len(duplicates) - 10} more" if len(duplicates) > 10 else ""
        errors.append(f"Keys used more than once: {shown}{more}")
    return parsed.columns, table, errors


def _load_table(name):
    """
    The parsed table of the given name: ``(columns, table)``, or None
    when there is no such table.
    """
    from application.models.lookup_table import LookupTable
    entry = LookupTable.objects(name=name).only('entries').first()
    if entry is None:
        return None
    columns, table, _errors = parse_lookup_table(entry.entries)
    return columns, table


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
    without it the second column is returned. An unknown table, key or
    column, or an empty cell, gives ``default``.
    """
    if key is None or isinstance(key, jinja2.Undefined):
        return default
    loaded = _get_table(table)
    if not loaded:
        return default
    columns, rows = loaded
    row = rows.get(str(key).strip())
    if row is None:
        return default
    if column is None:
        column = columns[1] if len(columns) > 1 else None
    return row.get(column) or default
