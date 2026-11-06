"""
Tests for moving rules between instances through a Git repository
"""
# pylint: disable=missing-function-docstring
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


def _load_git_staging():
    """
    Load git_staging.py from disk against stubbed neighbours. The stubs
    only live while the module is executed, so other tests keep seeing
    their own versions of the rule modules.
    """
    package = types.ModuleType('application.plugins.rules')
    package.__path__ = []
    get_account = types.ModuleType('application.helpers.get_account')
    get_account.AccountNotFoundError = type('AccountNotFoundError', (Exception,), {})
    get_account.get_account_by_name = MagicMock()
    definitions = types.ModuleType('application.plugins.rules.rule_definitions')
    definitions.rules = {}
    import_export = types.ModuleType('application.plugins.rules.rule_import_export')
    for name in ('_model_class_for', '_queryset_filter_for', 'import_rule_lines',
                 'iter_rules_of_type'):
        setattr(import_export, name, MagicMock())
    import_export.ACCOUNTS_RULE_TYPE = 'accounts'
    import_export.HOST_COLLECTION_RULE_TYPE = 'host_objects'
    import_export.PASSWORDS_RULE_TYPE = 'cmk_passwords'
    import_export.USERS_RULE_TYPE = 'users'
    stubs = {
        'application.plugins.rules': package,
        'application.helpers.get_account': get_account,
        'application.plugins.rules.rule_definitions': definitions,
        'application.plugins.rules.rule_import_export': import_export,
    }
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'git_staging.py')
    spec = importlib.util.spec_from_file_location(
        'application.plugins.rules.git_staging', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


gs = _load_git_staging()

RULES = {
    'cmk_filter': [
        '{"_id": {"$oid": "b2"}, "name": "second"}',
        '{"_id": {"$oid": "a1"}, "name": "first"}',
    ],
    'cmk_rules': ['{"_id": {"$oid": "c3"}, "name": "third"}'],
}
REGISTRY = {name: ('module', 'Model') for name in
            ['cmk_filter', 'cmk_rules', 'accounts', 'users', 'cmk_passwords',
             'host_objects']}


class TestGitStaging(unittest.TestCase):
    """Push into and pull from a local bare repository"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.remote = os.path.join(self.tmp.name, 'remote.git')
        subprocess.run(['git', 'init', '--bare', '--quiet', self.remote], check=True)
        self.account = {'typ': 'git', 'address': self.remote, 'username': '',
                        'password': '', 'branch': 'main', 'path': 'rules'}
        patches = [
            patch.object(gs, 'enabled_rules', REGISTRY),
            patch.object(gs, 'get_account_by_name', lambda name: dict(self.account)),
            patch.object(gs, 'iter_rules_of_type', lambda rule_type: iter(RULES[rule_type])),
            patch.object(gs, 'log', MagicMock()),
        ]
        for entry in patches:
            entry.start()
            self.addCleanup(entry.stop)
        self.addCleanup(self.tmp.cleanup)

    def remote_file(self, name):
        return subprocess.run(['git', '--git-dir', self.remote, 'show', f'main:{name}'],
                              check=True, capture_output=True, text=True).stdout

    def test_staging_types_leave_out_instance_data(self):
        self.assertEqual(gs.staging_rule_types(), ['cmk_filter', 'cmk_rules'])

    def test_push_creates_branch_with_sorted_rules(self):
        result = gs.push_rules('git', ['cmk_filter'])
        self.assertTrue(result['commit'])
        self.assertEqual(result['changed'], ['rules/cmk_filter.json'])
        rules = json.loads(self.remote_file('rules/cmk_filter.json'))
        self.assertEqual([x['name'] for x in rules], ['first', 'second'])

    def test_push_without_change_creates_no_commit(self):
        gs.push_rules('git', ['cmk_filter'])
        self.assertEqual(gs.push_rules('git', ['cmk_filter']),
                         {'changed': [], 'commit': None})

    def test_push_keeps_other_types(self):
        gs.push_rules('git', ['cmk_filter'])
        gs.push_rules('git', ['cmk_rules'])
        self.assertIn('first', self.remote_file('rules/cmk_filter.json'))
        self.assertIn('third', self.remote_file('rules/cmk_rules.json'))

    def test_push_refuses_excluded_types(self):
        with self.assertRaises(gs.GitStagingError):
            gs.push_rules('git', ['accounts'])

    def _commit_to_remote(self, change):
        """Put what *change* creates in a checkout onto the remote branch."""
        with tempfile.TemporaryDirectory() as tmp:
            checkout = os.path.join(tmp, 'c')
            subprocess.run(['git', 'clone', '-q', self.remote, checkout], check=True,
                           capture_output=True)
            subprocess.run(['git', '-C', checkout, 'checkout', '-q', '-B', 'main'],
                           check=True, capture_output=True)
            change(checkout)
            subprocess.run(['git', '-C', checkout, 'add', '--all'], check=True)
            subprocess.run(['git', '-C', checkout, '-c', 'user.name=x', '-c',
                            'user.email=x@example.com', 'commit', '-q', '-m', 'evil'],
                           check=True, capture_output=True)
            subprocess.run(['git', '-C', checkout, 'push', '-q', 'origin', 'main'],
                           check=True, capture_output=True)

    def test_a_rule_file_that_is_a_link_is_refused(self):
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as victim:
            victim.write('[]')
        self.addCleanup(os.unlink, victim.name)
        rule_type = 'cmk_filter'

        def add_link(checkout):
            os.makedirs(os.path.join(checkout, 'rules'))
            os.symlink(victim.name, os.path.join(checkout, 'rules', f'{rule_type}.json'))

        self._commit_to_remote(add_link)
        with self.assertRaisesRegex(gs.GitStagingError, 'symbolic link'):
            gs.push_rules('git', [rule_type])
        with open(victim.name, encoding='utf-8') as victim_file:
            self.assertEqual(victim_file.read(), '[]')
        with self.assertRaisesRegex(gs.GitStagingError, 'symbolic link'):
            gs.pull_rules('git')

    def test_a_rule_folder_leading_out_is_refused(self):
        with tempfile.TemporaryDirectory() as outside:
            def add_link(checkout):
                os.symlink(outside, os.path.join(checkout, 'rules'))

            self._commit_to_remote(add_link)
            with self.assertRaisesRegex(gs.GitStagingError, 'leads out'):
                gs.push_rules('git', ['cmk_filter'])
            self.assertEqual(os.listdir(outside), [])
            with self.assertRaisesRegex(gs.GitStagingError, 'leads out'):
                gs.pull_rules('git')

    def test_push_needs_a_rule_type(self):
        with self.assertRaises(gs.GitStagingError):
            gs.push_rules('git', [])

    def test_wrong_account_type(self):
        self.account['typ'] = 'checkmk'
        with self.assertRaises(gs.GitStagingError):
            gs.push_rules('git', ['cmk_filter'])

    def test_path_must_stay_inside_repository(self):
        self.account['path'] = '../outside'
        with self.assertRaises(gs.GitStagingError):
            gs.push_rules('git', ['cmk_filter'])

    def test_pull_missing_branch(self):
        with self.assertRaises(gs.GitStagingError):
            gs.pull_rules('git')

    def test_pull_imports_every_type_with_override(self):
        gs.push_rules('git', ['cmk_filter', 'cmk_rules'])
        importer = MagicMock(side_effect=lambda rules, default_rule_type, override:
                             {default_rule_type: len(rules)})
        with patch.object(gs, 'import_rule_lines', importer), \
                patch.object(gs, '_delete_missing') as delete:
            result = gs.pull_rules('git')
        delete.assert_not_called()
        self.assertEqual(result['types']['cmk_filter'],
                         {'total': 2, 'deleted': 0, 'imported': 2})
        self.assertEqual(result['types']['cmk_rules']['imported'], 1)
        for call in importer.call_args_list:
            self.assertTrue(call.kwargs['override'])

    def test_pull_selected_types_and_delete_missing(self):
        gs.push_rules('git', ['cmk_filter'])
        importer = MagicMock(return_value={'cmk_filter': 2})
        with patch.object(gs, 'import_rule_lines', importer), \
                patch.object(gs, '_delete_missing', return_value=3) as delete:
            result = gs.pull_rules('git', ['cmk_filter', 'cmk_rules'],
                                   delete_missing=True)
        delete.assert_called_once_with('cmk_filter', ['a1', 'b2'])
        self.assertEqual(result['types']['cmk_filter']['deleted'], 3)
        self.assertEqual(result['missing'], ['cmk_rules'])
        self.assertIn('Not in the repository: cmk_rules',
                      gs.format_pull_result(result))

    def test_pull_reports_error_per_type(self):
        gs.push_rules('git', ['cmk_filter'])
        with patch.object(gs, 'import_rule_lines', side_effect=ValueError('broken')):
            result = gs.pull_rules('git')
        self.assertEqual(result['types']['cmk_filter']['error'], 'broken')

    def test_address_is_never_read_as_an_option(self):
        marker = os.path.join(self.tmp.name, 'marker')
        self.account['address'] = f'--upload-pack=touch {marker}'
        for run in (lambda: gs.push_rules('git', ['cmk_filter']),
                    lambda: gs.pull_rules('git', ['cmk_filter'])):
            with self.assertRaises(gs.GitStagingError):
                run()
        self.assertFalse(os.path.exists(marker))

    def test_checkout_ends_the_options_before_the_address(self):
        marker = os.path.join(self.tmp.name, 'marker')
        config = gs.repo_config('git')
        config['url'] = f'--upload-pack=touch {marker}'
        workdir = os.path.join(self.tmp.name, 'work')
        with self.assertRaises(gs.GitStagingError):
            gs._checkout(config, workdir, create_missing=False)  # pylint: disable=protected-access
        self.assertFalse(os.path.exists(marker))

    def test_checkout_still_clones_with_a_normal_address(self):
        gs.push_rules('git', ['cmk_filter'])
        workdir = os.path.join(self.tmp.name, 'work')
        gs._checkout(gs.repo_config('git'), workdir, create_missing=False)  # pylint: disable=protected-access
        self.assertTrue(os.path.exists(os.path.join(workdir, 'rules', 'cmk_filter.json')))

    def test_token_is_not_on_the_command_line(self):
        self.account.update(username='user', password='secret-token')
        config = gs.repo_config('git')
        completed = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        with patch.object(gs.subprocess, 'run', return_value=completed) as run:
            gs._git(config, 'ls-remote', 'url')  # pylint: disable=protected-access
        command = run.call_args.args[0]
        env = run.call_args.kwargs['env']
        self.assertNotIn('secret-token', ' '.join(command))
        self.assertEqual(env['GIT_CONFIG_KEY_0'], 'http.extraHeader')
        self.assertTrue(env['GIT_CONFIG_VALUE_0'].startswith('Authorization: Basic '))


if __name__ == '__main__':
    unittest.main()
