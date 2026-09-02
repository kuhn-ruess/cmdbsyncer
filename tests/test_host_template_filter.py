"""
Host-list filter for CMDB template assignment.

The "CMDB Template" filter group has two operations: "contains"
matches a template by name, "is" answers the two fleet-wide questions
— which hosts have any template at all, and which have none.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest

from bson import ObjectId

from application.views.host_filters import (
    FilterCmdbTemplate,
    FilterHasCmdbTemplate,
)


class _Query:  # pylint: disable=too-few-public-methods
    """Records what the filter hands to the mongoengine query."""

    def __init__(self):
        self.applied = None
        self.args = ()

    def filter(self, *args, **kwargs):
        self.applied = kwargs
        self.args = args
        return self


class HasCmdbTemplateFilterTest(unittest.TestCase):
    """application.views.host_filters.FilterHasCmdbTemplate"""

    def setUp(self):
        self.flt = FilterHasCmdbTemplate.__new__(FilterHasCmdbTemplate)

    def _applied(self, value):
        query = _Query()
        self.flt.apply(query, value)
        return query.applied

    def test_yes_matches_hosts_with_a_template(self):
        self.assertEqual(
            self._applied('yes'),
            {'__raw__': {'cmdb_templates.0': {'$exists': True}}},
        )

    def test_no_matches_hosts_without_a_template(self):
        # `cmdb_templates.0` misses for all three empty shapes: field
        # absent, null, and empty list.
        self.assertEqual(
            self._applied('no'),
            {'__raw__': {'cmdb_templates.0': {'$exists': False}}},
        )

    def test_empty_value_leaves_the_query_untouched(self):
        query = _Query()
        self.assertIs(self.flt.apply(query, ''), query)
        self.assertIsNone(query.applied)

    def test_operation_is_a_choice(self):
        self.assertEqual(self.flt.operation(), 'is')


class CmdbTemplateFilterTest(unittest.TestCase):
    """application.views.host_filters.FilterCmdbTemplate"""

    def setUp(self):
        self.flt = FilterCmdbTemplate.__new__(FilterCmdbTemplate)

    def test_it_filters_with_a_field_query_not_a_raw_one(self):
        """
        A template-restricted user already carries a `cmdb_templates`
        condition from their scope. mongoengine merges a `__raw__`
        query into the query dict by key, so the two collapsed into one
        and the filter silently did nothing — the list stayed the whole
        scope. Two field queries on the same field become `$and`.
        """
        oid = ObjectId('0' * 24)
        query = _Query()
        self.flt.apply(query, str(oid))
        self.assertEqual(query.applied, {})
        self.assertEqual(len(query.args), 1)
        self.assertEqual(query.args[0].query, {'cmdb_templates__in': [oid]})

    def test_empty_value_leaves_the_query_untouched(self):
        query = _Query()
        self.assertIs(self.flt.apply(query, '  '), query)
        self.assertIsNone(query.applied)

    def test_operation_is_contains(self):
        self.assertEqual(self.flt.operation(), 'contains')
