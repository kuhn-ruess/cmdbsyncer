"""
Unit tests for checkmk groups module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from mongoengine.errors import DoesNotExist
from application.plugins.checkmk.groups import CheckmkGroupSync
from tests import base_mock_init


class TestCheckmkGroupSync(unittest.TestCase):
    """Tests for CheckmkGroupSync"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param,
                           config={'settings': {}, 'ref': 'account_ref'})

        self.init_patcher = patch(
            'application.plugins.checkmk.groups.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.sync = CheckmkGroupSync()

    def tearDown(self):
        self.init_patcher.stop()

    @patch('application.plugins.checkmk.groups.CheckmkObjectCache')
    def test_get_cache_object_existing(self, mock_cache_cls):
        mock_obj = Mock()
        mock_cache_cls.objects.get.return_value = mock_obj

        result = self.sync.get_cache_object('contact_groups')
        self.assertEqual(result, mock_obj)

    @patch('application.plugins.checkmk.groups.CheckmkObjectCache')
    def test_get_cache_object_new(self, mock_cache_cls):
        mock_cache_cls.objects.get.side_effect = DoesNotExist()
        mock_new = Mock()
        mock_cache_cls.return_value = mock_new

        result = self.sync.get_cache_object('host_groups')
        self.assertEqual(result.cache_group, 'host_groups')
        self.assertEqual(result.account, 'account_ref')

    def test_add_group_entries_basic(self):
        groups = {'contact_groups': []}
        outcome = Mock()
        outcome.rewrite = None
        outcome.rewrite_title = None

        self.sync._add_group_entries(
            items=['group1', 'group2'],
            rewrite_name=False,
            rewrite_title=False,
            outcome=outcome,
            group_type='contact_groups',
            groups=groups,
            str_replace=lambda x, exc: x,
            replace_exceptions=['-', '_'],
        )

        self.assertEqual(len(groups['contact_groups']), 2)
        self.assertIn(('group1', 'group1'), groups['contact_groups'])
        self.assertIn(('group2', 'group2'), groups['contact_groups'])

    @patch('application.plugins.checkmk.groups.render_jinja')
    def test_add_group_entries_with_rewrite(self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: f"rewritten_{kw['name']}"

        groups = {'host_groups': []}
        outcome = Mock()
        outcome.rewrite = 'tpl_name'
        outcome.rewrite_title = 'tpl_title'

        self.sync._add_group_entries(
            items=['item1'],
            rewrite_name=True,
            rewrite_title=True,
            outcome=outcome,
            group_type='host_groups',
            groups=groups,
            str_replace=lambda x, exc: x,
            replace_exceptions=['-', '_'],
        )

        self.assertEqual(len(groups['host_groups']), 1)
        title, name = groups['host_groups'][0]
        self.assertEqual(name, 'rewritten_item1')
        self.assertEqual(title, 'rewritten_item1')

    def test_add_group_entries_no_duplicates(self):
        groups = {'contact_groups': [('g1', 'g1')]}
        outcome = Mock()

        self.sync._add_group_entries(
            items=['g1'],
            rewrite_name=False,
            rewrite_title=False,
            outcome=outcome,
            group_type='contact_groups',
            groups=groups,
            str_replace=lambda x, exc: x,
            replace_exceptions=['-', '_'],
        )

        self.assertEqual(len(groups['contact_groups']), 1)

    def test_add_group_entries_empty_name_skipped(self):
        groups = {'contact_groups': []}
        outcome = Mock()

        self.sync._add_group_entries(
            items=[''],
            rewrite_name=False,
            rewrite_title=False,
            outcome=outcome,
            group_type='contact_groups',
            groups=groups,
            str_replace=lambda x, exc: x.strip(),
            replace_exceptions=['-', '_'],
        )

        self.assertEqual(len(groups['contact_groups']), 0)

    @patch('application.plugins.checkmk.groups.Host')
    def test_parse_attributes(self, mock_host):
        mock_db_host1 = Mock()
        mock_db_host2 = Mock()
        mock_host.get_export_hosts.return_value = [mock_db_host1, mock_db_host2]

        with patch.object(self.sync, 'get_attributes') as mock_get:
            mock_get.side_effect = [
                {'all': {'os': 'linux', 'env': 'prod'}},
                {'all': {'os': 'windows', 'env': 'prod'}},
            ]
            keys, values = self.sync.parse_attributes()

        self.assertIn('os', keys)
        self.assertIn('linux', keys['os'])
        self.assertIn('windows', keys['os'])
        self.assertIn('prod', values)
        self.assertIn('env', values['prod'])

    @patch('application.plugins.checkmk.groups.Host')
    def test_parse_attributes_skips_no_attributes(self, mock_host):
        mock_db_host = Mock()
        mock_host.get_export_hosts.return_value = [mock_db_host]

        with patch.object(self.sync, 'get_attributes', return_value=None):
            keys, values = self.sync.parse_attributes()

        self.assertEqual(keys, {})
        self.assertEqual(values, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
