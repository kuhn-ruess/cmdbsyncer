"""
Merged CMDB template values.

By default a template only fills gaps: the host's own data wins and the
first template that provides a key wins over later ones. A field marked
"merge" in the template form breaks that rule — the attribute is then
collected from every template the host carries, comma separated, so
several templates can contribute to one value (contact groups, tags,
service lists). Marking it in one of the templates is enough.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from application.models.host_templates import (
    merge_attribute_values, template_merge_keys,
)
from tests.plugin_helpers import plain_plugin


def _field(name, merge=False):
    return SimpleNamespace(field_name=name, field_value='x', merge=merge)


def _template(hostname, labels, merge_keys=()):
    tmpl = Mock()
    tmpl.hostname = hostname
    tmpl.deleted_at = None
    tmpl.labels = labels
    tmpl.cmdb_fields = [_field(key, key in merge_keys) for key in labels]
    return tmpl


class TestTemplateMergeKeys(unittest.TestCase):

    def test_only_ticked_rows_merge(self):
        tmpl = SimpleNamespace(cmdb_fields=[
            _field('contact_groups', merge=True),
            _field('os'),
        ])
        self.assertEqual(template_merge_keys(tmpl), {'contact_groups'})

    def test_template_without_rows_merges_nothing(self):
        self.assertEqual(template_merge_keys(SimpleNamespace()), set())
        self.assertEqual(template_merge_keys(SimpleNamespace(cmdb_fields=[])),
                         set())


class TestMergeAttributeValues(unittest.TestCase):

    def test_values_are_comma_joined(self):
        self.assertEqual(merge_attribute_values('ops', 'dba'), 'ops,dba')

    def test_existing_lists_are_kept_in_order(self):
        self.assertEqual(merge_attribute_values('ops,dba', 'net'),
                         'ops,dba,net')

    def test_duplicates_are_dropped(self):
        self.assertEqual(merge_attribute_values('ops,dba', 'dba, net'),
                         'ops,dba,net')

    def test_empty_parts_disappear(self):
        self.assertEqual(merge_attribute_values('', 'ops'), 'ops')
        self.assertEqual(merge_attribute_values(None, 'ops'), 'ops')
        self.assertEqual(merge_attribute_values('ops', ' , '), 'ops')

    def test_non_string_values_are_stringified(self):
        self.assertEqual(merge_attribute_values(1, 2), '1,2')


class TestMergedTemplateAttributes(unittest.TestCase):

    mock_app_config = {
        'REPLACERS': [],
        'LOWERCASE_ATTRIBUTE_KEYS': False,
        'REPLACE_ATTRIBUTE_KEYS': False,
        'LABELS_ITERATE_FIRST_LEVEL': False,
    }

    @staticmethod
    def _host(labels, templates):
        host = Mock()
        host.hostname = 'web01'
        host.cache = {}
        host.labels = labels
        host.inventory = {}
        host.cmdb_templates = templates
        return host

    @patch('application.modules.plugin.app')
    def test_merged_field_collects_every_template(self, mock_app):
        mock_app.config = self.mock_app_config
        first = _template('base', {'contact_groups': 'ops'},
                          merge_keys=('contact_groups',))
        second = _template('db', {'contact_groups': 'dba'},
                           merge_keys=('contact_groups',))
        host = self._host({}, [first, second])

        result = plain_plugin().get_attributes(host, False)

        self.assertEqual(result['all']['contact_groups'], 'ops,dba')

    @patch('application.modules.plugin.app')
    def test_merged_field_appends_to_the_host_value(self, mock_app):
        mock_app.config = self.mock_app_config
        tmpl = _template('db', {'contact_groups': 'dba'},
                         merge_keys=('contact_groups',))
        host = self._host({'contact_groups': 'ops'}, [tmpl])

        result = plain_plugin().get_attributes(host, False)

        # The host stays in front — merging adds, it never reorders.
        self.assertEqual(result['all']['contact_groups'], 'ops,dba')

    @patch('application.modules.plugin.app')
    def test_unmarked_field_still_collides(self, mock_app):
        mock_app.config = self.mock_app_config
        first = _template('base', {'os': 'linux'})
        second = _template('other', {'os': 'windows'})
        host = self._host({}, [first, second])

        result = plain_plugin().get_attributes(host, False)

        self.assertEqual(result['all']['os'], 'linux')

    @patch('application.modules.plugin.app')
    def test_one_marked_template_merges_all_of_them(self, mock_app):
        """The flag describes the key, not the template that carries it."""
        mock_app.config = self.mock_app_config
        first = _template('a', {'ops': 'a'}, merge_keys=('ops',))
        second = _template('b', {'ops': 'b'})
        third = _template('c', {'ops': 'c'})
        host = self._host({}, [first, second, third])

        result = plain_plugin().get_attributes(host, False)

        self.assertEqual(result['all']['ops'], 'a,b,c')

    @patch('application.modules.plugin.app')
    def test_marking_the_last_template_merges_all_of_them(self, mock_app):
        mock_app.config = self.mock_app_config
        first = _template('a', {'ops': 'a'})
        second = _template('b', {'ops': 'b'})
        third = _template('c', {'ops': 'c'}, merge_keys=('ops',))
        host = self._host({}, [first, second, third])

        result = plain_plugin().get_attributes(host, False)

        self.assertEqual(result['all']['ops'], 'a,b,c')

    @patch('application.modules.plugin.app')
    def test_merged_field_alone_behaves_like_a_normal_value(self, mock_app):
        mock_app.config = self.mock_app_config
        tmpl = _template('base', {'contact_groups': 'ops'},
                         merge_keys=('contact_groups',))
        host = self._host({}, [tmpl])

        result = plain_plugin().get_attributes(host, False)

        self.assertEqual(result['all']['contact_groups'], 'ops')


if __name__ == '__main__':
    unittest.main()
