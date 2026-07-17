"""
Unit tests for assign_cmdb_template_from_folder
"""
# pylint: disable=missing-function-docstring
import unittest
from unittest.mock import patch, MagicMock

from application.plugins.checkmk.inits import assign_cmdb_template_from_folder


def _make_host_objects(template, hosts):
    """Build a Host.objects side effect: template lookup + per-host lookup."""
    def objects_side_effect(**kwargs):
        query = MagicMock()
        if kwargs.get('object_type') == 'template':
            query.first.return_value = template
        else:
            query.first.return_value = hosts.get(kwargs.get('hostname'))
        return query
    return objects_side_effect


class TestAssignTemplateFromFolder(unittest.TestCase):
    """Tests for assign_cmdb_template_from_folder"""

    @patch('application.plugins.checkmk.inits.CMK2')
    @patch('application.plugins.checkmk.inits.Host')
    def test_merges_and_skips(self, mock_host, mock_cmk2):
        template = MagicMock(id='tmpl-id')
        host_a = MagicMock(cmdb_templates=[])          # gets the template
        host_b = MagicMock(cmdb_templates=[template])  # already has it
        mock_host.objects.side_effect = _make_host_objects(
            template, {'host_a': host_a, 'host_b': host_b})  # host_c: not in syncer

        cmk_inst = MagicMock()
        cmk_inst.get_hosts_of_folder.return_value = {
            'host_a': {}, 'host_b': {}, 'host_c': {}}
        mock_cmk2.return_value = cmk_inst

        assigned = assign_cmdb_template_from_folder('acc', '/f', 'TMPL')

        self.assertEqual(assigned, 1)
        cmk_inst.get_hosts_of_folder.assert_called_once_with('/f', '')
        # host_a merged and saved
        self.assertIn(template, host_a.cmdb_templates)
        host_a.save.assert_called_once()
        # host_b already had it -> untouched
        host_b.save.assert_not_called()

    @patch('application.plugins.checkmk.inits.CMK2')
    @patch('application.plugins.checkmk.inits.Host')
    def test_template_missing_aborts(self, mock_host, mock_cmk2):
        mock_host.objects.side_effect = _make_host_objects(None, {})

        assigned = assign_cmdb_template_from_folder('acc', '/f', 'NOPE')

        self.assertEqual(assigned, 0)
        # Never contacted Checkmk, never touched a host
        mock_cmk2.assert_not_called()

    @patch('application.plugins.checkmk.inits.CMK2')
    @patch('application.plugins.checkmk.inits.Host')
    def test_dry_run_does_not_save(self, mock_host, mock_cmk2):
        template = MagicMock(id='tmpl-id')
        host_a = MagicMock(cmdb_templates=[])
        mock_host.objects.side_effect = _make_host_objects(
            template, {'host_a': host_a})

        cmk_inst = MagicMock()
        cmk_inst.get_hosts_of_folder.return_value = {'host_a': {}}
        mock_cmk2.return_value = cmk_inst

        assigned = assign_cmdb_template_from_folder(
            'acc', '/f', 'TMPL', dry_run=True)

        self.assertEqual(assigned, 1)
        host_a.save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
