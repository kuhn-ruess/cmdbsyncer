"""
Unit tests for checkmk tags module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.tags import CheckmkTagSync
from tests import base_mock_init


class TestCheckmkTagSync(unittest.TestCase):
    """Tests for CheckmkTagSync"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param, groups={})

        self.init_patcher = patch(
            'application.plugins.checkmk.tags.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.sync = CheckmkTagSync()

    def tearDown(self):
        self.init_patcher.stop()

    def test_create_inital_groups_basic(self):
        rule = Mock()
        rule.group_id = 'grp1'
        rule.group_topic_name = 'Topic'
        rule.group_title = 'Group 1'
        rule.group_help = 'Help text'
        rule.rewrite_id = '{{ HOSTNAME }}'
        rule.rewrite_title = '{{ HOSTNAME }}'
        rule.filter_by_account = ''
        rule.group_multiply_list = ''
        rule.group_multiply_by_list = False

        groups = {}
        multiply_expressions = []

        self.sync.create_inital_groups(rule, groups, multiply_expressions)

        self.assertIn('grp1', groups)
        self.assertEqual(groups['grp1']['title'], 'Group 1')
        self.assertEqual(groups['grp1']['topic'], 'Topic')
        self.assertFalse(groups['grp1']['is_template'])
        self.assertEqual(len(multiply_expressions), 0)

    def test_create_inital_groups_with_multiply(self):
        rule = Mock()
        rule.group_id = 'grp1'
        rule.group_topic_name = 'Topic'
        rule.group_title = 'Group 1'
        rule.group_help = ''
        rule.rewrite_id = '{{ name }}'
        rule.rewrite_title = '{{ name }}'
        rule.filter_by_account = ''
        rule.group_multiply_list = '{{ sites }}'
        rule.group_multiply_by_list = True

        groups = {}
        multiply_expressions = []

        self.sync.create_inital_groups(rule, groups, multiply_expressions)

        self.assertTrue(groups['grp1']['is_template'])
        self.assertEqual(len(multiply_expressions), 1)
        self.assertEqual(multiply_expressions[0], ('grp1', '{{ sites }}'))

    def test_prepare_tags_for_checkmk_empty(self):
        result = self.sync.prepare_tags_for_checkmk([])
        self.assertFalse(result)

    def test_prepare_tags_for_checkmk_none(self):
        result = self.sync.prepare_tags_for_checkmk(None)
        self.assertFalse(result)

    def test_prepare_tags_for_checkmk_single(self):
        tags = [('id1', 'Title 1')]
        result = self.sync.prepare_tags_for_checkmk(tags)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], {'ident': 'id1', 'title': 'Title 1'})

    def test_prepare_tags_for_checkmk_multiple_adds_not_set(self):
        tags = [('id1', 'Title 1'), ('id2', 'Title 2')]
        result = self.sync.prepare_tags_for_checkmk(tags)
        # First entry should be "Not set"
        self.assertEqual(result[0], {'ident': None, 'title': 'Not set'})
        self.assertEqual(len(result), 3)

    def test_prepare_tags_for_checkmk_deduplicates(self):
        tags = [('id1', 'Title 1'), ('id1', 'Title 1 Dup')]
        result = self.sync.prepare_tags_for_checkmk(tags)
        idents = [t['ident'] for t in result if t['ident'] is not None]
        self.assertEqual(len(idents), 1)

    def test_prepare_tags_for_checkmk_strips(self):
        tags = [('  id1  ', '  Title 1  ')]
        result = self.sync.prepare_tags_for_checkmk(tags)
        self.assertEqual(result[0]['ident'], 'id1')
        self.assertEqual(result[0]['title'], 'Title 1')

    def test_prepare_tags_skips_empty_title(self):
        tags = [('id1', '  ')]
        result = self.sync.prepare_tags_for_checkmk(tags)
        self.assertFalse(result)

    def test_get_checkmk_tags(self):
        response = ({
            'value': [
                {
                    'id': 'grp1',
                    'extensions': {'tags': [{'id': 't1', 'title': 'Tag 1'}]}
                },
                {
                    'id': 'grp2',
                    'extensions': {'tags': []}
                }
            ]
        }, {'ETag': 'etag123'})

        with patch.object(self.sync, 'request', return_value=response):
            etag, checkmk_ids = self.sync.get_checkmk_tags()

        self.assertEqual(etag, 'etag123')
        self.assertIn('grp1', checkmk_ids)
        self.assertEqual(len(checkmk_ids['grp1']), 1)
        self.assertIn('grp2', checkmk_ids)

    def test_update_hosts_tags(self):
        db_host = Mock()
        db_host.cache = {
            'cmk_tags_tag_choices': {
                'grp1': ('tag_id', 'Tag Title'),
            }
        }
        global_tags = []

        self.sync.update_hosts_tags(db_host, global_tags)

        self.assertEqual(len(global_tags), 1)
        self.assertEqual(global_tags[0], ('grp1', 'tag_id', 'Tag Title'))

    def test_update_hosts_tags_no_cache(self):
        db_host = Mock()
        db_host.cache = {}
        global_tags = []

        self.sync.update_hosts_tags(db_host, global_tags)
        self.assertEqual(len(global_tags), 0)

    def test_update_hosts_tags_no_duplicates(self):
        db_host = Mock()
        db_host.cache = {
            'cmk_tags_tag_choices': {
                'grp1': ('tag_id', 'Tag Title'),
            }
        }
        global_tags = [('grp1', 'tag_id', 'Tag Title')]

        self.sync.update_hosts_tags(db_host, global_tags)
        self.assertEqual(len(global_tags), 1)

    def test_update_hosts_multigroups_no_cache(self):
        db_host = Mock()
        db_host.cache = {}
        groups = {}

        self.sync.update_hosts_multigroups(db_host, groups)
        self.assertEqual(groups, {})

    def test_update_hosts_multigroups_updates(self):
        db_host = Mock()
        db_host.cache = {
            'cmk_tags_multigroups': {
                'new_grp': {
                    'title': 'New Group',
                    'is_template': True,
                }
            }
        }
        groups = {}

        self.sync.update_hosts_multigroups(db_host, groups)
        self.assertIn('new_grp', groups)
        self.assertFalse(groups['new_grp']['is_template'])

    @patch('application.plugins.checkmk.tags.render_jinja')
    @patch('application.plugins.checkmk.tags.cmk_cleanup_tag_id')
    def test_get_tags_for_host(self, mock_cleanup, mock_render):
        mock_render.side_effect = lambda tpl, **kw: 'rendered'
        mock_cleanup.return_value = 'rendered'

        db_object = Mock()
        db_object.hostname = 'host1'
        object_attributes = {'all': {'HOSTNAME': 'host1'}}
        groups = {
            'grp1': {
                'rw_id': '{{ HOSTNAME }}',
                'rw_title': '{{ HOSTNAME }}',
            }
        }

        result = self.sync.get_tags_for_host(
            db_object, object_attributes, groups, {})

        self.assertIn('grp1', result)
        self.assertEqual(result['grp1'], ('rendered', 'rendered'))

    @patch('application.plugins.checkmk.tags.render_jinja')
    @patch('application.plugins.checkmk.tags.cmk_cleanup_tag_id')
    def test_get_tags_for_host_skips_templates(self, mock_cleanup, mock_render):
        db_object = Mock()
        db_object.hostname = 'host1'
        groups = {
            'grp1': {'is_template': True}
        }

        result = self.sync.get_tags_for_host(
            db_object, {'all': {}}, groups, {})

        self.assertNotIn('grp1', result)

    @patch('application.plugins.checkmk.tags.render_jinja')
    @patch('application.plugins.checkmk.tags.cmk_cleanup_tag_id')
    def test_get_tags_for_host_uses_tags_of_host(self, mock_cleanup, mock_render):
        db_object = Mock()
        db_object.hostname = 'host1'
        groups = {'grp1': {}}
        tags_of_host = {'grp1': ('pre_id', 'Pre Title')}

        result = self.sync.get_tags_for_host(
            db_object, {'all': {}}, groups, tags_of_host)

        self.assertEqual(result['grp1'], ('pre_id', 'Pre Title'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
