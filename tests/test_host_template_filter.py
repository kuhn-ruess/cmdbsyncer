"""
Host-list filter for CMDB template assignment.

The "CMDB Template" filter group has two operations: "contains"
matches a template by name, "is" answers the two fleet-wide questions
— which hosts have any template at all, and which have none.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest

from application.views.host_filters import FilterHasCmdbTemplate


class _Query:  # pylint: disable=too-few-public-methods
    """Records the kwargs the filter hands to the mongoengine query."""

    def __init__(self):
        self.applied = None

    def filter(self, **kwargs):
        self.applied = kwargs
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
