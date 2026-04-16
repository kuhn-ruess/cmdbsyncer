"""
Unit tests for checkmk helpers module
"""
# pylint: disable=missing-function-docstring
import unittest
from unittest.mock import patch

from application.plugins.checkmk.helpers import (
    cmk_cleanup_tag_id, cmk_cleanup_tag_value, cmk_cleanup_hostname,
)


class TestCmkCleanupTagId(unittest.TestCase):
    """Tests for cmk_cleanup_tag_id"""

    @patch('application.plugins.checkmk.helpers.app')
    def test_basic_cleanup(self, mock_app):
        mock_app.config = {'CMK_JINJA_USE_REPLACERS': False}
        result = cmk_cleanup_tag_id('hello-world_123')
        self.assertEqual(result, 'hello-world_123')

    @patch('application.plugins.checkmk.helpers.app')
    def test_removes_invalid_chars(self, mock_app):
        mock_app.config = {'CMK_JINJA_USE_REPLACERS': False}
        result = cmk_cleanup_tag_id('hello world!@#$%')
        self.assertEqual(result, 'hello_world_____')

    @patch('application.plugins.checkmk.helpers.app')
    def test_lowercase(self, mock_app):
        mock_app.config = {'CMK_JINJA_USE_REPLACERS': False}
        result = cmk_cleanup_tag_id('UPPERCASE')
        self.assertEqual(result, 'uppercase')

    @patch('application.plugins.checkmk.helpers.app')
    def test_strips_whitespace(self, mock_app):
        mock_app.config = {'CMK_JINJA_USE_REPLACERS': False}
        # strip() is called first, then regex replaces remaining invalid chars
        result = cmk_cleanup_tag_id('  hello  ')
        self.assertEqual(result, 'hello')

    @patch('application.plugins.checkmk.helpers.app')
    def test_with_replacers(self, mock_app):
        mock_app.config = {
            'CMK_JINJA_USE_REPLACERS': True,
            'REPLACERS': [('ä', 'ae'), ('ö', 'oe')],
        }
        result = cmk_cleanup_tag_id('ärger')
        self.assertEqual(result, 'aerger')


class TestCmkCleanupTagValue(unittest.TestCase):
    """Tests for cmk_cleanup_tag_value"""

    @patch('application.plugins.checkmk.helpers.app')
    def test_basic_cleanup(self, mock_app):
        mock_app.config = {'CMK_JINJA_USE_REPLACERS': False}
        result = cmk_cleanup_tag_value('Valid-Value_123')
        self.assertEqual(result, 'valid-value_123')

    @patch('application.plugins.checkmk.helpers.app')
    def test_removes_special_chars(self, mock_app):
        mock_app.config = {'CMK_JINJA_USE_REPLACERS': False}
        result = cmk_cleanup_tag_value('hello.world/test')
        self.assertEqual(result, 'hello_world_test')

    @patch('application.plugins.checkmk.helpers.app')
    def test_with_replacers(self, mock_app):
        mock_app.config = {
            'CMK_JINJA_USE_REPLACERS': True,
            'REPLACERS': [('ü', 'ue')],
        }
        result = cmk_cleanup_tag_value('über')
        self.assertEqual(result, 'ueber')


class TestCmkCleanupHostname(unittest.TestCase):
    """Tests for cmk_cleanup_hostname"""

    @patch('application.plugins.checkmk.helpers.app')
    def test_basic_cleanup(self, mock_app):
        mock_app.config = {'CMK_JINJA_USE_REPLACERS_FOR_HOSTNAMES': False}
        result = cmk_cleanup_hostname('my-host_01')
        self.assertEqual(result, 'my-host_01')

    @patch('application.plugins.checkmk.helpers.app')
    def test_removes_dots(self, mock_app):
        mock_app.config = {'CMK_JINJA_USE_REPLACERS_FOR_HOSTNAMES': False}
        result = cmk_cleanup_hostname('host.example.com')
        self.assertEqual(result, 'host_example_com')

    @patch('application.plugins.checkmk.helpers.app')
    def test_with_replacers(self, mock_app):
        mock_app.config = {
            'CMK_JINJA_USE_REPLACERS_FOR_HOSTNAMES': True,
            'REPLACERS': [('.', '-')],
        }
        result = cmk_cleanup_hostname('host.example.com')
        self.assertEqual(result, 'host-example-com')

    @patch('application.plugins.checkmk.helpers.app')
    def test_lowercase_output(self, mock_app):
        mock_app.config = {'CMK_JINJA_USE_REPLACERS_FOR_HOSTNAMES': False}
        result = cmk_cleanup_hostname('MyHost')
        self.assertEqual(result, 'myhost')


if __name__ == '__main__':
    unittest.main(verbosity=2)
