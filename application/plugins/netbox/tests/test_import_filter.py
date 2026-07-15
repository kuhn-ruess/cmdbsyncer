"""
Unit tests for the Netbox parse_import_filter helper
"""
# pylint: disable=missing-function-docstring
import unittest

from application.plugins.netbox.utils import parse_import_filter


class TestParseImportFilter(unittest.TestCase):
    """import_filter string -> Netbox API kwargs."""

    def test_single_value_stays_string(self):
        # Backward compatible: one value per key is a plain string.
        self.assertEqual(
            parse_import_filter('role:router'),
            {'role': 'router'},
        )

    def test_repeated_key_becomes_or_list(self):
        self.assertEqual(
            parse_import_filter('role:router,role:firewall'),
            {'role': ['router', 'firewall']},
        )

    def test_mixed_single_and_multi(self):
        self.assertEqual(
            parse_import_filter('role:router,role:firewall,status:active'),
            {'role': ['router', 'firewall'], 'status': 'active'},
        )

    def test_whitespace_and_empty_segments_ignored(self):
        self.assertEqual(
            parse_import_filter(' role:router , , status:active '),
            {'role': 'router', 'status': 'active'},
        )

    def test_value_may_contain_colon(self):
        # split on the first colon only.
        self.assertEqual(
            parse_import_filter('name:host:01'),
            {'name': 'host:01'},
        )

    def test_segment_without_colon_is_skipped(self):
        self.assertEqual(parse_import_filter('role'), {})


if __name__ == '__main__':
    unittest.main()
