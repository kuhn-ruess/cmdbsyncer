"""
Unit tests for reading Jira Assets attribute values
"""
# pylint: disable=missing-function-docstring
import unittest

from application.plugins.jira_cloud.jira_cloud import JiraCloud


class TestAttributeValue(unittest.TestCase):
    """Tests for JiraCloud.attribute_value"""

    def test_default_type_uses_value(self):
        entry = {'value': 'srv01', 'displayValue': 'srv01'}
        self.assertEqual(JiraCloud.attribute_value(entry), 'srv01')

    def test_status_attribute_is_read(self):
        # A Status attribute has no 'value' key at all; reading it made the
        # export see the field as unset and rewrite it on every run.
        entry = {
            'status': {'id': 3, 'name': 'toolsOk', 'category': 1},
            'displayValue': 'toolsOk',
        }
        self.assertEqual(JiraCloud.attribute_value(entry), 'toolsOk')

    def test_status_attribute_without_display_value(self):
        entry = {'status': {'id': 3, 'name': 'toolsOk', 'category': 1}}
        self.assertEqual(JiraCloud.attribute_value(entry), 'toolsOk')

    def test_reference_attribute_falls_back_to_label(self):
        entry = {'referencedObject': {'id': 7, 'label': 'esx-cluster-1'}}
        self.assertEqual(JiraCloud.attribute_value(entry), 'esx-cluster-1')

    def test_user_attribute_falls_back_to_display_name(self):
        entry = {'user': {'key': 'abc', 'displayName': 'Jane Doe'}}
        self.assertEqual(JiraCloud.attribute_value(entry), 'Jane Doe')

    def test_unknown_shape_returns_none(self):
        self.assertIsNone(JiraCloud.attribute_value({'searchValue': '3'}))
