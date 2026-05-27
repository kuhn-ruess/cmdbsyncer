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
from application.modules.search_parser import parse_search, SearchSyntaxError

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


class FilterStale(BaseMongoEngineFilter):
    """
    Boolean filter: 'yes' shows only hosts the `mark_stale` job has
    flagged, 'no' shows only fresh hosts.
    """

    def apply(self, query, value):
        value = (value or '').strip().lower()
        if value in ('1', 'yes', 'y', 'true'):
            return query.filter(is_stale=True)
        if value in ('0', 'no', 'n', 'false'):
            return query.filter(is_stale__ne=True)
        return query

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

    def _search(self, query, search_term):
        """
        Run the user-typed expression through the Lucene-flavoured
        search parser. A bare term still matches hostname/labels/
        inventory like before; boolean operators (AND/OR/NOT, `!`,
        parentheses) and `field:value` pairs extend that. Malformed
        input flashes a message and yields an empty result instead of
        raising — the form re-renders with the user's expression intact
        so they can fix it.
        """
        try:
            pipeline = parse_search(search_term)
        except SearchSyntaxError as error:
            flash(f"Search syntax error: {error}", 'danger')
            return query.filter(hostname=None)
        if pipeline is None:
            return query
        filtered = query.filter(__raw__=pipeline)
        # Eagerly run a tiny query so a regex that compiles in Python
        # but trips MongoDB's PCRE engine (e.g. an unbalanced character
        # class buried under a NOT, or a value Mongo refuses for other
        # reasons) is surfaced as a flash message instead of a 500
        # later in Flask-Admin's count/iterate loop. `.first()` is the
        # cheapest probe — Mongo aborts the query on the bad regex
        # before scanning, regardless of collection size.
        try:
            filtered.first()
        except Exception as error:  # pylint: disable=broad-exception-caught
            flash(f"Search rejected by database: {error}", 'danger')
            return query.filter(hostname=None)
        return filtered
