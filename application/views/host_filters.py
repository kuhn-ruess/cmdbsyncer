"""
Flask-Admin Mongo filters used by the Host model views.

Extracted from `application.views.host` so the main module no longer
hosts ~190 lines of unrelated filter plumbing. Filters live in their
own file because they only depend on Mongo regex/key validation, not
on any of the ModelView wiring.
"""
import re
from bson import ObjectId
from bson.errors import InvalidId
from flask import flash
from flask_admin.contrib.mongoengine.filters import BaseMongoEngineFilter

from application.models.host import Host

FILTER_KEY_RE = re.compile(r'^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$')


def _validate_filter_key(key):
    clean_key = key.strip()
    if not FILTER_KEY_RE.fullmatch(clean_key):
        raise ValueError("Invalid filter key")
    return clean_key


def _compile_filter_regex(value):
    """
    Validate a user-supplied regex for a Key:Value label/inventory
    filter. The filter operation is advertised as "regex search", so
    the raw value is used verbatim — we only size-limit it and confirm
    it compiles, matching the hostname-filter precedent.
    """
    if len(value) > 500:
        raise ValueError("Filter value too long")
    re.compile(value)
    return value


class FilterAccountRegex(BaseMongoEngineFilter):
    """
    Filter Value with Regex
    """

    def apply(self, query, value):
        return query.filter(source_account_name__icontains=value)

    def operation(self):
        return "contains"


class FilterHostnameRegex(BaseMongoEngineFilter):
    """
    Filter Value with Regex
    """

    def apply(self, query, value):
        if len(value) > 1000:
            return query.filter(hostname=None)
        try:
            regex = re.compile(value)
        except re.error:
            return query.filter(hostname=None)
        return query.filter(hostname=regex)

    def operation(self):
        return "regex"


class FilterObjectType(BaseMongoEngineFilter):
    """
    Filter Value
    """

    def apply(self, query, value):
        return query.filter(object_type__icontains=value)

    def operation(self):
        return "contains"


class FilterLifecycleState(BaseMongoEngineFilter):
    """
    Filter hosts by Lifecycle State. Empty/missing rows are treated as
    'active' so the legacy fleet maps onto the new state machine
    without a one-shot migration.
    """

    def apply(self, query, value):
        value = (value or '').strip().lower()
        if not value:
            return query
        if value == 'active':
            return query.filter(__raw__={
                '$or': [
                    {'lifecycle_state': 'active'},
                    {'lifecycle_state': {'$exists': False}},
                    {'lifecycle_state': None},
                    {'lifecycle_state': ''},
                ]
            })
        return query.filter(lifecycle_state=value)

    def operation(self):
        return "is"


class FilterPoolFolder(BaseMongoEngineFilter):
    """
    Filter Value
    """

    def apply(self, query, value):
        return query.filter(folder__icontains=value)

    def operation(self):
        return "contains"


class FilterCmdbTemplate(BaseMongoEngineFilter):
    """
    Filter hosts by an assigned CMDB template. Accepts either a
    template ObjectId (24-char hex — used by the click-to-filter icon
    next to each template badge) or a case-insensitive substring of a
    template hostname. The click case is exact; the typed case is
    fuzzy. Uses a `__raw__` `$in` query because mongoengine's
    `cmdb_templates__in=[oid]` keyword form has bitten us before with
    `ListField(ReferenceField)` storage.
    """

    def apply(self, query, value):
        value = (value or '').strip()
        if not value:
            return query

        ids = []
        try:
            ids = [ObjectId(value)]
        except (InvalidId, TypeError):
            templates = Host.objects(
                object_type='template',
                hostname__icontains=value,
            ).only('id')
            ids = [t.id for t in templates]

        if not ids:
            # No template matched — short-circuit to an empty result.
            return query.filter(hostname=None)
        return query.filter(__raw__={'cmdb_templates': {'$in': ids}})

    def operation(self):
        return "contains"


def _build_keyvalue_pipeline(field, value):
    """
    Build a MongoDB `$or` pipeline for a "key:value" label/inventory
    filter. The string branch uses `$regex` so users can actually pass
    regex syntax (the filter is advertised as "regex search"); the
    numeric and boolean branches use exact equality, because BSON
    numbers and booleans are **not** string-matchable with `$regex` —
    which is why `input_monitoring:True` used to find nothing.
    """
    regex_value = _compile_filter_regex(value)
    or_clauses = [{field: {"$regex": regex_value, "$options": "i"}}]

    try:
        or_clauses.append({field: int(value)})
    except ValueError:
        pass

    lower = value.lower()
    if lower in ('true', 'yes'):
        or_clauses.append({field: True})
    elif lower in ('false', 'no'):
        or_clauses.append({field: False})

    if len(or_clauses) == 1:
        return or_clauses[0]
    return {"$or": or_clauses}


class FilterLabelKeyAndValue(BaseMongoEngineFilter):
    """
    Filter Key:Value Pair for Label
    """

    def apply(self, query, value):
        try:
            key, value = value.split(':', 1)
            key = _validate_filter_key(key)
            value = value.strip()

            # Filter for None values, but only if key exists
            if value.lower() == 'none':
                pipeline = {
                    "$and": [
                        {f"labels.{key}": None},
                        {f"labels.{key}": {"$exists": True}}
                    ]
                }
                return query.filter(__raw__=pipeline)

            pipeline = _build_keyvalue_pipeline(f'labels.{key}', value)
            return query.filter(__raw__=pipeline)
        except Exception as error:  # pylint: disable=broad-exception-caught
            flash(str(error), 'danger')
        return False

    def operation(self):
        return "regex search"


class FilterInventoryKeyAndValue(BaseMongoEngineFilter):
    """
    Filter Key:Value Pair for Inventory
    """

    def apply(self, query, value):
        try:
            key, value = value.split(':', 1)
            key = _validate_filter_key(key)
            value = value.strip()

            # Filter for None values, but only if key exists
            if value.lower() == 'none':
                pipeline = {
                    "$and": [
                        {f"inventory.{key}": None},
                        {f"inventory.{key}": {"$exists": True}}
                    ]
                }
                return query.filter(__raw__=pipeline)

            pipeline = _build_keyvalue_pipeline(f'inventory.{key}', value)
            return query.filter(__raw__=pipeline)
        except Exception as error:  # pylint: disable=broad-exception-caught
            flash(str(error), 'danger')
        return False

    def operation(self):
        return "regex search"


class HostnameAndLabelSearchMixin:  # pylint: disable=too-few-public-methods
    """
    Top-right quick-search box that matches `hostname` OR any value
    in `labels` OR any value in `inventory`. Shared by HostModelView
    and ObjectModelView so both list pages behave identically —
    Objects' cmdb_fields are mirrored into `labels` by
    `update_host()`, so the same query covers them.
    """

    column_searchable_list = ['hostname']

    def init_search(self):
        """
        Bypass Flask-Admin's strict `type(p) in allowed_search_types`
        check — flask-mongoengine wraps StringField in a subclass that
        fails identity comparison. We only need the search box to
        render; `_search()` drives the actual query.
        """
        for name in self.column_searchable_list or []:
            field = self.model._fields.get(name) if isinstance(name, str) else name
            if field is None:
                raise ValueError(f"Invalid search field: {name!r}")
            self._search_fields.append(field)
        return bool(self._search_fields)

    @staticmethod
    def _dict_value_match_expr(field_name, term):
        """`$expr` that regex-matches any value of a dict-typed field."""
        return {'$expr': {
            '$anyElementTrue': {
                '$map': {
                    'input': {'$objectToArray': {
                        '$ifNull': [f'${field_name}', {}],
                    }},
                    'as': 'kv',
                    'in': {
                        '$regexMatch': {
                            'input': {
                                '$convert': {
                                    'input': '$$kv.v',
                                    'to': 'string',
                                    'onError': '',
                                    'onNull': '',
                                },
                            },
                            'regex': term,
                            'options': 'i',
                        },
                    },
                },
            },
        }}

    def _search(self, query, search_term):
        """
        Match hostname OR any label value OR any inventory value
        against the term. Falls back to a literal match if the user
        typed something that doesn't compile as a regex.
        """
        term = (search_term or '').strip()
        if not term:
            return query
        try:
            re.compile(term)
        except re.error:
            term = re.escape(term)
        pipeline = {
            '$or': [
                {'hostname': {'$regex': term, '$options': 'i'}},
                self._dict_value_match_expr('labels', term),
                self._dict_value_match_expr('inventory', term),
            ],
        }
        return query.filter(__raw__=pipeline)
