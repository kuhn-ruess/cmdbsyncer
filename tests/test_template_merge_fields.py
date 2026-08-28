"""
Merged attributes across CMDB templates.

By default a template only fills gaps: the host's own data wins and the
first template that provides a key wins over later ones. An attribute
listed as merged in the System Config breaks that rule — it is then
collected from every template the host carries, comma separated, so
several templates can contribute to one value (contact groups, tags,
service lists). The list is configured centrally, so editing a template
can never change how another template behaves.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest
from unittest.mock import Mock, patch

from application.models.host_templates import merge_attribute_values

from tests.plugin_helpers import plain_plugin


def _template(hostname, labels):
    tmpl = Mock()
    tmpl.hostname = hostname
    tmpl.deleted_at = None
    tmpl.labels = labels
    return tmpl


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

    def _attributes(self, host, merged=()):
        with patch('application.modules.plugin.app') as mock_app:
            mock_app.config = self.mock_app_config
            plugin = plain_plugin(merged_attributes=merged)
            return plugin.get_attributes(host, False)['all']

    def test_merged_attribute_collects_every_template(self):
        host = self._host({}, [_template('a', {'ops': 'a'}),
                               _template('b', {'ops': 'b'}),
                               _template('c', {'ops': 'c'})])

        result = self._attributes(host, merged=('ops',))

        self.assertEqual(result['ops'], 'a,b,c')

    def test_merged_attribute_appends_to_the_host_value(self):
        host = self._host({'contact_groups': 'ops'},
                          [_template('db', {'contact_groups': 'dba'})])

        result = self._attributes(host, merged=('contact_groups',))

        # The host stays in front — merging adds, it never reorders.
        self.assertEqual(result['contact_groups'], 'ops,dba')

    def test_unlisted_attribute_still_collides(self):
        host = self._host({}, [_template('base', {'os': 'linux'}),
                               _template('other', {'os': 'windows'})])

        result = self._attributes(host, merged=('contact_groups',))

        self.assertEqual(result['os'], 'linux')

    def test_merged_attribute_alone_behaves_like_a_normal_value(self):
        host = self._host({}, [_template('base', {'ops': 'a'})])

        result = self._attributes(host, merged=('ops',))

        self.assertEqual(result['ops'], 'a')

    def test_the_config_is_read_once_per_plugin(self):
        host = self._host({}, [_template('base', {'ops': 'a'})])
        with patch('application.modules.plugin.app') as mock_app, \
             patch('application.modules.plugin.merged_attribute_keys',
                   return_value={'ops'}) as keys:
            mock_app.config = self.mock_app_config
            plugin = plain_plugin()
            plugin.merged_attributes = None  # nothing loaded yet
            plugin.get_attributes(host, False)
            host.cache = {}
            plugin.get_attributes(host, False)

        keys.assert_called_once()

    def test_a_host_without_templates_never_reads_the_config(self):
        host = self._host({'os': 'linux'}, [])
        with patch('application.modules.plugin.app') as mock_app, \
             patch('application.modules.plugin.merged_attribute_keys') as keys:
            mock_app.config = self.mock_app_config
            plugin = plain_plugin()
            plugin.merged_attributes = None
            plugin.get_attributes(host, False)

        keys.assert_not_called()


if __name__ == '__main__':
    unittest.main()
