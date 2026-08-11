"""
Label editing in the host / object admin forms.

Deleting a label in the web UI means emptying its row (or removing it
with the ✕ button). Both have to make the label disappear — the bug
these tests guard against is a "deleted" label coming back stored with
an empty value.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_api import import_host_module


class _CmdbField:  # pylint: disable=too-few-public-methods
    """Stand-in for the CmdbField embedded document."""

    def __init__(self):
        self.field_name = None
        self.field_value = None


class LabelsFromCmdbFormTest(unittest.TestCase):
    """application.views.host._labels_from_cmdb_form"""

    def setUp(self):
        self.host_module = import_host_module()

    def _labels(self, rows):
        return self.host_module._labels_from_cmdb_form(rows)  # pylint: disable=protected-access

    def test_full_rows_become_labels(self):
        self.assertEqual(
            self._labels([{'field_name': 'os', 'field_value': 'linux'}]),
            {'os': 'linux'},
        )

    def test_emptied_value_deletes_the_label(self):
        self.assertEqual(self._labels([{'field_name': 'os', 'field_value': ''}]), {})

    def test_whitespace_only_value_deletes_the_label(self):
        self.assertEqual(self._labels([{'field_name': 'os', 'field_value': '  '}]), {})

    def test_emptied_name_drops_the_row(self):
        self.assertEqual(self._labels([{'field_name': '', 'field_value': 'linux'}]), {})

    def test_missing_value_drops_the_row(self):
        # Configured CMDB model fields render without a value.
        self.assertEqual(self._labels([{'field_name': 'owner', 'field_value': None}]), {})

    def test_boolean_false_is_kept(self):
        # A boolean CMDB model field submits False — that is a value.
        self.assertEqual(
            self._labels([{'field_name': 'monitored', 'field_value': False}]),
            {'monitored': False},
        )

    def test_values_are_stripped(self):
        self.assertEqual(
            self._labels([{'field_name': ' os ', 'field_value': ' linux '}]),
            {'os': 'linux'},
        )


class RebuildCmdbFieldsTest(unittest.TestCase):
    """application.views.host._rebuild_cmdb_fields"""

    def setUp(self):
        self.host_module = import_host_module()

    def _rebuild(self, model, configured=None):
        with patch.object(self.host_module, 'CmdbField', _CmdbField), \
             patch.object(self.host_module, 'get_cmdb_model_fields',
                          lambda _object_type='host': dict(configured or {})):
            self.host_module._rebuild_cmdb_fields(model)  # pylint: disable=protected-access
        return [(f.field_name, f.field_value) for f in model.cmdb_fields]

    def test_deleted_label_leaves_no_empty_row(self):
        # 'site' was emptied in the form: it is gone from labels, so it
        # must not survive as an empty cmdb_fields row either — that row
        # would come back as a label with an empty value on the next save.
        model = SimpleNamespace(
            object_type='host',
            labels={'os': 'linux'},
            cmdb_fields=[],
        )
        self.assertEqual(self._rebuild(model), [('os', 'linux')])

    def test_configured_fields_stay_as_empty_placeholders(self):
        model = SimpleNamespace(object_type='host', labels={'os': 'linux'}, cmdb_fields=[])
        self.assertEqual(
            self._rebuild(model, configured={'owner': {'type': 'string'}}),
            [('os', 'linux'), ('owner', '')],
        )

    def test_rows_are_sorted_case_insensitively(self):
        model = SimpleNamespace(
            object_type='host',
            labels={'Zone': 'dmz', 'os': 'linux'},
            cmdb_fields=[],
        )
        self.assertEqual(self._rebuild(model), [('os', 'linux'), ('Zone', 'dmz')])

    def test_non_string_values_are_stringified(self):
        model = SimpleNamespace(object_type='host', labels={'monitored': False}, cmdb_fields=[])
        self.assertEqual(self._rebuild(model), [('monitored', 'False')])


if __name__ == '__main__':
    unittest.main()
