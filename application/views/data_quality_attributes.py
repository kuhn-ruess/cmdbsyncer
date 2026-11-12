"""
Data Quality: Attribute Values.

Which values an attribute (label or inventory key) has across the live
hosts and on how many hosts each one appears. Without a name the page lists
every attribute with its number of hosts and values; with a name, exact or
as a prefix, it lists the values of each matching attribute. Values that
only differ in case or white space are marked, they are usually the same
thing spelled twice.

Mongo does the counting in one aggregation, so even large installations
need no pass over every host in Python. Building the pipeline and shaping
its result are pure functions, tested without Mongo.
"""
import json
import re

from application.modules.rule.match import MAX_REGEX_LENGTH
from application.views.host_filters import FILTER_KEY_RE

FIELDS = {'labels': 'Labels', 'inventory': 'Inventory'}
MODES = {'prefix': 'starts with', 'exact': 'is exactly'}
# Values listed per attribute; the rest is counted, not shown.
VALUE_LIMIT = 500


def name_regex(name, mode):
    """The case-insensitive key regex for ``name``, None for all keys."""
    name = (name or '').strip()
    if not name:
        return None
    return '^' + re.escape(name) + ('$' if mode == 'exact' else '')


def build_pipeline(field, regex, with_values):
    """
    The aggregation over the live hosts (no objects, nothing archived).
    Groups by attribute and value; ``with_values=False`` adds a second
    group so only one row per attribute comes back.
    """
    pipeline = [
        {'$match': {'is_object': {'$ne': True}, 'deleted_at': {'$exists': False}}},
        {'$project': {'_id': 0,
                      'kv': {'$objectToArray': {'$ifNull': [f'${field}', {}]}}}},
        {'$unwind': '$kv'},
    ]
    if regex:
        pipeline.append({'$match': {'kv.k': {'$regex': regex, '$options': 'i'}}})
    pipeline.append({'$group': {'_id': {'k': '$kv.k', 'v': '$kv.v'},
                                'hosts': {'$sum': 1}}})
    if not with_values:
        pipeline.append({'$group': {'_id': '$_id.k', 'hosts': {'$sum': '$hosts'},
                                    'values': {'$sum': 1}}})
    return pipeline


def display_value(value):
    """A value as text: lists and dicts as JSON, None as empty."""
    if value is None:
        return ''
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def filter_value(key, value):
    """
    The ``key:value`` of the host list filter "Label Key:Value" that finds
    exactly this value, None when the filter cannot express it (lists,
    dicts, a key the filter refuses, a value too long). The filter ignores
    case.
    """
    if not FILTER_KEY_RE.fullmatch(key):
        return None
    if value is None:
        return f'{key}:none'
    if isinstance(value, bool):
        return f"{key}:{'yes' if value else 'no'}"
    if isinstance(value, (list, dict)):
        return None
    pattern = f'^{re.escape(str(value))}$'
    if len(pattern) > MAX_REGEX_LENGTH:
        return None
    return f'{key}:{pattern}'


def _variant_key(text):
    return ' '.join(text.split()).lower()


def overview(rows):
    """Rows of the attribute-only pipeline as ``{'name', 'hosts', 'distinct'}``."""
    return sorted(({'name': row['_id'], 'hosts': row['hosts'],
                    'distinct': row['values']} for row in rows),
                  key=lambda row: row['name'].lower())


def attribute_values(rows, limit=VALUE_LIMIT):
    """
    Rows of the value pipeline as one dict per attribute: ``name``,
    ``hosts`` (hosts carrying it), ``distinct`` (number of values),
    ``values`` (the ``limit`` most frequent ones, all for None, each with ``display``,
    ``hosts``, ``filter`` and ``variant``: another value differs only in
    case, white space or type, like 5 and "5") and ``hidden`` (values not listed).
    """
    by_key = {}
    for row in rows:
        by_key.setdefault(row['_id']['k'], []).append(
            (row['_id'].get('v'), row['hosts']))
    result = []
    for key in sorted(by_key, key=str.lower):
        values = sorted(by_key[key], key=lambda pair: (-pair[1],
                                                       display_value(pair[0])))
        variants = {}
        for value, _hosts in values:
            text = display_value(value)
            # The type counts too: 5 and "5", or None and "", are variants.
            variants.setdefault(_variant_key(text), set()).add(
                (text, type(value).__name__))
        result.append({
            'name': key,
            'hosts': sum(hosts for _value, hosts in values),
            'distinct': len(values),
            'hidden': max(0, len(values) - limit) if limit else 0,
            'values': [{
                'display': display_value(value),
                'empty': value is None or value == '',
                'hosts': hosts,
                'filter': filter_value(key, value),
                'variant': len(variants[_variant_key(display_value(value))]) > 1,
            } for value, hosts in values[:limit or None]],
        })
    return result


def collect(field, name, mode, limit=VALUE_LIMIT):
    """
    Run the aggregation and return ``(overview_rows, attributes)``, the
    one that does not apply is None. ``limit`` as in :func:`attribute_values`.
    """
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    if field not in FIELDS:
        field = 'labels'
    regex = name_regex(name, mode)
    rows = Host.objects.aggregate(build_pipeline(field, regex, bool(regex)),
                                  allowDiskUse=True)
    if regex:
        return None, attribute_values(rows, limit)
    return overview(rows), None


def live_host_count():
    """Number of live hosts, the base for "on X of Y hosts"."""
    # pylint: disable=import-outside-toplevel
    from application.models.host import Host
    return Host.objects(is_object__ne=True, deleted_at__exists=False).count()
