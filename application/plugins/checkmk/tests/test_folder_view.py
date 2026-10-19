"""
Checkmk Folders page: folders, folder option merge and its debug.
"""
# pylint: disable=missing-function-docstring
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.folder_view import (
    FolderCalculation,
    build_folders,
    folder_prefixes,
    host_contributions,
    merge_trace,
    rule_owners,
    scope_folders,
    subtree_hosts,
)

CG_A = "/shared|{'contactgroups': {'groups': ['team_a'], 'use': True}}"
CG_B = "/shared|{'contactgroups': {'groups': ['team_b', 'team_a'], 'use': False}}"


def _actions(move, options=None):
    actions = {'move_folder': move}
    if options:
        actions['extra_folder_options'] = options
    return actions


class TestFolders(unittest.TestCase):
    """build_folders and its helpers"""

    def test_prefixes(self):
        self.assertEqual(folder_prefixes('/a/b'), ['/a', '/a/b'])
        self.assertEqual(folder_prefixes('/'), [])

    def test_host_contributions_per_level(self):
        found = host_contributions(
            'host1', _actions('/a/b', "/a|{'title': 'A'}/b|{'site': 's1'}"))
        self.assertEqual([(c['folder'], c['level'], c['attributes']) for c in found],
                         [('/a', 0, {'title': 'A'}), ('/a/b', 1, {'site': 's1'})])

    def test_host_contributions_without_options(self):
        self.assertEqual(host_contributions('host1', _actions('/a', '/a')), [])

    def test_unset_values_are_dropped(self):
        found = host_contributions('host1', _actions('/a', "/a|{'city': False}"))
        self.assertEqual(found[0]['attributes'], {})
        self.assertEqual(found[0]['dropped'], ['city'])

    def test_merge_like_the_export(self):
        folders = build_folders([('host1', _actions('/shared', CG_A)),
                                 ('host2', _actions('/shared', CG_B))])
        shared = folders['/shared']
        self.assertEqual(shared['hosts'], ['host1', 'host2'])
        self.assertEqual(shared['attributes'], {
            'contactgroups': {'groups': ['team_a', 'team_b'], 'use': True}})
        first, second = shared['trace']
        self.assertEqual({n['path']: n['effect'] for n in first},
                         {'contactgroups.groups': 'set', 'contactgroups.use': 'set'})
        effects = [(n['path'], n['effect'], n['value']) for n in second]
        self.assertIn(('contactgroups.groups', 'added', ['team_b']), effects)
        self.assertIn(('contactgroups.groups', 'present', ['team_a']), effects)
        self.assertIn(('contactgroups.use', 'ignored', False), effects)

    def test_merge_matches_syncer(self):
        """The page shows the value the export would send."""
        # pylint: disable-next=import-outside-toplevel
        from application.plugins.checkmk.syncer import SyncCMK2
        syncer = SyncCMK2.__new__(SyncCMK2)
        syncer.custom_folder_attributes = {}
        syncer.dropped_folder_values = {}
        syncer.log_details = []
        for value in (CG_A, CG_B):
            syncer.handle_extra_folder_options(value)
        folders = build_folders([('h1', _actions('/shared', CG_A)),
                                 ('h2', _actions('/shared', CG_B))])
        self.assertEqual(folders['/shared']['attributes'],
                         syncer.custom_folder_attributes['/shared'])

    def test_broken_option_is_noted(self):
        _, notes = merge_trace(host_contributions(
            'h1', _actions('/a', "/a|{'title': 'A'}}")))
        self.assertEqual(notes[0][0]['effect'], 'broken')

    def test_parents_and_root_exist(self):
        folders = build_folders([('h1', _actions('/a/b')), ('h2', {})])
        self.assertEqual(sorted(folders), ['/', '/a', '/a/b'])
        self.assertEqual(folders['/']['hosts'], ['h2'])
        self.assertEqual(subtree_hosts(folders, '/a'), ['h1'])
        self.assertEqual(sorted(subtree_hosts(folders, '/')), ['h1', 'h2'])

    def test_create_folder_counts(self):
        folders = build_folders([('h1', {
            'create_folder': '/empty',
            'create_folder_extra_folder_options': "/empty|{'title': 'E'}"})])
        self.assertEqual(folders['/empty']['attributes'], {'title': 'E'})
        self.assertEqual(folders['/empty']['contributions'][0]['kind'], 'create')


class TestScope(unittest.TestCase):
    """A restricted user sees only the folders and values of their hosts"""

    def setUp(self):
        self.folders = build_folders([
            ('host_a', _actions('/shared', CG_A)),
            ('host_b', _actions('/shared', CG_B)),
            ('host_c', _actions('/other/deep')),
        ])

    def test_unrestricted_unchanged(self):
        self.assertIs(scope_folders(self.folders, None), self.folders)

    def test_restricted(self):
        scoped = scope_folders(self.folders, {'host_a'})
        self.assertEqual(sorted(scoped), ['/', '/shared'])
        shared = scoped['/shared']
        self.assertEqual(shared['hosts'], ['host_a'])
        self.assertEqual(shared['hidden_hosts'], 1)
        self.assertEqual(shared['hidden_contributions'], 1)
        # No contact group of the hidden host leaks.
        self.assertEqual(shared['attributes'], {
            'contactgroups': {'groups': ['team_a'], 'use': True}})

    def test_parent_of_visible_host(self):
        scoped = scope_folders(self.folders, {'host_c'})
        self.assertEqual(sorted(scoped), ['/', '/other', '/other/deep'])
        self.assertEqual(scoped['/']['hosts'], [])

    def test_nothing_visible(self):
        self.assertEqual(scope_folders(self.folders, set()), {})


class TestRuleOwners(unittest.TestCase):
    """Which Export Rule put which folder level there"""

    def test_levels_per_rule(self):
        lines = [
            {'hit': True, 'name': 'r1', 'outcome': {'extra_folder_options': '/a'}},
            {'hit': False, 'name': 'r2', 'outcome': {}},
            {'hit': True, 'name': 'r3', 'outcome': {
                'extra_folder_options': "/a/b|{'title': 'B'}"}},
            {'hit': True, 'name': 'r4', 'outcome': {'parents': ['x']}},
        ]
        owners = rule_owners(lines)
        self.assertEqual(owners[('move', 0)]['name'], 'r1')
        self.assertEqual(owners[('move', 1)]['name'], 'r3')
        self.assertEqual(len(owners), 2)


class TestFolderCalculation(unittest.TestCase):
    """The calculation is read only"""

    def _calculation(self, hosts, config=None):
        syncer = Mock()
        syncer.config = config or {}
        syncer.name = 'Undefined'
        syncer.get_attributes.side_effect = \
            lambda host, cache, persist_cache: {'all': {'team': host.team}}
        syncer.actions.get_outcomes.side_effect = \
            lambda host, attrs, **kw: _actions('/shared', CG_A)
        syncer._host_result_exported.return_value = True  # pylint: disable=protected-access
        syncer.use_host.return_value = True
        syncer.project_denied_for_account.return_value = False
        with patch('application.plugins.checkmk.syncer.SyncCMK2',
                   return_value=syncer) as sync_class, \
                patch('application.plugins.checkmk._load_rules', create=True,
                      return_value={'filter': 'f', 'rewrite': 'r', 'actions': 'a'}), \
                patch('application.plugins.checkmk.rules.host_folder_engine',
                      return_value=syncer.actions):
            calculation = FolderCalculation('acc')
        sync_class.assert_called_once_with('acc', probe_version=False)
        calculation._hosts = lambda: hosts  # pylint: disable=protected-access
        return calculation, syncer

    def test_no_save_no_cache(self):
        host = Mock(hostname='h1', team='team_a', project=None)
        calculation, syncer = self._calculation([host])
        calculation.run()
        host.save.assert_not_called()
        syncer.flush_host_cache.assert_not_called()
        syncer.get_attributes.assert_called_once_with(host, False, persist_cache=False)
        syncer.actions.get_outcomes.assert_called_once_with(
            host, {'team': 'team_a'}, persist_cache=False, use_cache=False)
        self.assertEqual(calculation.folders()['/shared']['hosts'], ['h1'])

    def test_account_selection_applies(self):
        hosts = [Mock(hostname='h1', team='a', project=None,
                      source_account_name='src'),
                 Mock(hostname='h2', team='b', project=None,
                      source_account_name='src')]
        calculation, syncer = self._calculation(hosts)
        syncer.use_host.side_effect = lambda name, _source: name == 'h1'
        syncer.project_denied_for_account.return_value = False
        calculation.run()
        self.assertEqual([r[0].hostname for r in calculation.results], ['h1'])

    def test_attribute_rules(self):
        host = Mock(hostname='h1', team='team_a', project=None)
        calculation, syncer = self._calculation([host])
        calculation.run()
        folder = calculation.folders()['/shared']

        def debug_run(*_args, **_kwargs):
            syncer.actions.debug_lines.append({
                'hit': True, 'id': 'rid', 'name': 'Rule A',
                'condition_type': 'all', 'match_reasons': [
                    {'match_type': 'tag', 'tag_match': 'equal', 'tag': 'team',
                     'value_match': 'equal', 'value': 'team_a'}],
                'outcome': {'extra_folder_options': CG_A}})
            return {}
        syncer.actions.get_outcomes.side_effect = debug_run
        with patch('application.plugins.checkmk.folder_view._folder_params',
                   return_value={'rid': [{'action': 'move_folder', 'param': 'x'}]}):
            calculation.attribute_rules(folder)
        rule = folder['contributions'][0]['rule']
        self.assertEqual(rule['name'], 'Rule A')
        self.assertIn("'team'", rule['conditions'][0])
        self.assertEqual(rule['params'][0]['action'], 'move_folder')
        self.assertFalse(syncer.actions.debug)
        host.save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
