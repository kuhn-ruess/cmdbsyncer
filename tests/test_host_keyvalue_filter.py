"""
Host-list Key:Value filters for labels, inventory and the Checkmk
attributes of the last sync.

All three share one implementation and only differ in the host field
they look into.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest
from unittest.mock import patch

from application.views import host_filters
from application.views.host_filters import (
    FilterCheckmkAttributeKeyAndValue,
    FilterInventoryKeyAndValue,
    FilterLabelKeyAndValue,
)

CHECKMK_PATH = 'cache.checkmk_hostattribute.attributes.all'


class _Query:  # pylint: disable=too-few-public-methods
    """Records what the filter hands to the mongoengine query."""

    def __init__(self):
        self.applied = None

    def filter(self, **kwargs):
        self.applied = kwargs
        return self


def _apply(flt_class, value):
    flt = flt_class.__new__(flt_class)
    query = _Query()
    flt.apply(query, value)
    return query.applied


class KeyAndValueFilterTest(unittest.TestCase):

    def test_value_is_matched_in_the_field_of_the_filter(self):
        cases = (
            (FilterLabelKeyAndValue, 'labels.vlan'),
            (FilterInventoryKeyAndValue, 'inventory.vlan'),
            (FilterCheckmkAttributeKeyAndValue, f'{CHECKMK_PATH}.vlan'),
        )
        for flt_class, path in cases:
            with self.subTest(flt_class.__name__), \
                    patch.object(host_filters, 'value_regex_query',
                                 return_value={'stub': path}) as query:
                applied = _apply(flt_class, 'vlan:5')
                query.assert_called_once_with(path, '5')
                self.assertEqual(applied, {'__raw__': {'stub': path}})

    def test_none_lists_hosts_with_an_empty_key(self):
        path = f'{CHECKMK_PATH}.vlan'
        self.assertEqual(
            _apply(FilterCheckmkAttributeKeyAndValue, 'vlan:none'),
            {'__raw__': {'$and': [
                {path: None},
                {path: {'$exists': True}},
            ]}},
        )

    def test_an_invalid_key_filters_nothing(self):
        with patch.object(host_filters, 'flash') as flash:
            flt = FilterCheckmkAttributeKeyAndValue.__new__(
                FilterCheckmkAttributeKeyAndValue)
            self.assertIs(flt.apply(_Query(), '$where:1'), False)
            flash.assert_called_once()


if __name__ == '__main__':
    unittest.main()
