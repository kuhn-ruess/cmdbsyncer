"""
The playbook runner has to work under a web user without a writable home.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
import os
import shutil
import sys
import tempfile
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

from tests import _load_real_module


def _load_runner():
    """Load the runner with its model import stubbed."""
    name = 'application.plugins.ansible.runner'
    if name in sys.modules:
        return sys.modules[name]
    models = sys.modules.setdefault(
        'application.plugins.ansible.models',
        ModuleType('application.plugins.ansible.models'))
    if not hasattr(models, 'AnsibleRunStats'):
        models.AnsibleRunStats = MagicMock()
    return _load_real_module(name, os.path.join(
        'plugins', 'ansible', 'runner.py'))


class SshEnvTest(unittest.TestCase):
    """
    $HOME does not reach OpenSSH — it expands `~/.ssh` via the passwd
    database — so the run has to name a writable known_hosts itself.
    """

    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()

    def test_known_hosts_points_into_the_run_dir(self):
        env = {}
        self.runner._apply_ssh_env(env, '/tmp/run-1')
        self.assertIn('-o UserKnownHostsFile=/tmp/run-1/known_hosts',
                      env['ANSIBLE_SSH_EXTRA_ARGS'])
        self.assertEqual(env['ANSIBLE_HOST_KEY_CHECKING'], 'False')

    def test_operator_settings_keep_precedence(self):
        env = {
            'ANSIBLE_HOST_KEY_CHECKING': 'True',
            'ANSIBLE_SSH_EXTRA_ARGS': '-o UserKnownHostsFile=/etc/ansible/known_hosts',
        }
        self.runner._apply_ssh_env(env, '/tmp/run-2')
        self.assertEqual(env['ANSIBLE_HOST_KEY_CHECKING'], 'True')
        # ssh keeps the first value given for an option, so the configured
        # file has to come before ours.
        args = env['ANSIBLE_SSH_EXTRA_ARGS']
        self.assertLess(args.index('/etc/ansible/known_hosts'),
                        args.index('/tmp/run-2/known_hosts'))


class AnsibleBinaryTest(unittest.TestCase):
    """
    Under systemd the venv's bin dir is not on PATH, so the runner has to
    find ansible-playbook next to the running interpreter.
    """

    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()

    def setUp(self):
        self.prefix = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.prefix)
        patcher = patch.object(self.runner.sys, 'prefix', self.prefix)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runner.app.config.pop('ANSIBLE_PLAYBOOK_BIN', None)

    def test_the_venv_binary_is_used(self):
        os.mkdir(os.path.join(self.prefix, 'bin'))
        binary = os.path.join(self.prefix, 'bin', 'ansible-playbook')
        with open(binary, 'w', encoding='utf-8'):
            pass
        self.assertEqual(self.runner._ansible_binary(), binary)

    def test_without_venv_binary_path_decides(self):
        self.assertEqual(self.runner._ansible_binary(), 'ansible-playbook')

    def test_the_config_wins(self):
        self.runner.app.config['ANSIBLE_PLAYBOOK_BIN'] = '/usr/bin/ansible-playbook'
        self.addCleanup(self.runner.app.config.pop, 'ANSIBLE_PLAYBOOK_BIN', None)
        self.assertEqual(self.runner._ansible_binary(), '/usr/bin/ansible-playbook')


class ConnectionHintTest(unittest.TestCase):
    """
    sshpass calls a non-writable home a wrong password. The log must not
    leave it at that.
    """

    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()

    def test_hint_added_for_unwritable_home(self):
        log = ('fatal: [host]: UNREACHABLE! => {"msg": "Invalid/incorrect '
               'password: Could not create directory \'/usr/share/httpd/.ssh\'."}')
        hint = self.runner._connection_hint(log)
        self.assertIn('NOT a wrong password', hint)

    def test_no_hint_for_a_real_password_failure(self):
        log = ('fatal: [host]: UNREACHABLE! => {"msg": "Invalid/incorrect '
               'password: Permission denied, please try again."}')
        self.assertEqual(self.runner._connection_hint(log), '')

    def test_no_hint_without_the_password_message(self):
        log = "Could not create directory '/usr/share/httpd/.ssh'."
        self.assertEqual(self.runner._connection_hint(log), '')


if __name__ == '__main__':
    unittest.main()


class PrivateKeyTest(unittest.TestCase):
    """The SSH key goes into a 0600 file of the run, never onto the argv"""

    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()

    def setUp(self):
        self.run_tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.run_tmp)

    def test_key_file_and_argument(self):
        params = {'playbook': 'site.yml', 'check_mode': False, 'target_host': None,
                  'extra_vars': None, 'ssh_user': 'srv01',
                  'ssh_private_key': 'KEYDATA'}
        files = self.runner._login_files(self.run_tmp, params)
        with patch.object(self.runner, '_ansible_dir', return_value=self.runner.Path('/a')), \
                patch.object(self.runner, '_ansible_binary', return_value='ansible-playbook'):
            cmd = self.runner._build_command('inv.yml', params, **files)
        key_file = files['key_file']
        self.assertEqual(cmd[cmd.index('--private-key') + 1], key_file)
        self.assertNotIn('KEYDATA', ' '.join(cmd))
        self.assertEqual(os.stat(key_file).st_mode & 0o777, 0o600)
        with open(key_file, encoding='utf-8') as handle:
            self.assertEqual(handle.read(), 'KEYDATA\n')

    def test_no_key_no_argument(self):
        params = {'playbook': 'site.yml', 'check_mode': False, 'target_host': None,
                  'extra_vars': None}
        files = self.runner._login_files(self.run_tmp, params)
        self.assertEqual(files, {'vars_file': None, 'key_file': None})


class BecomePasswordTest(unittest.TestCase):
    """The sudo password goes into the 0600 vars file, never onto the argv"""

    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()

    def setUp(self):
        self.run_tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.run_tmp)

    def _vars(self, **login):
        params = {'playbook': 'site.yml', 'check_mode': False, 'target_host': None,
                  'extra_vars': None, **login}
        files = self.runner._login_files(self.run_tmp, params)
        with patch.object(self.runner, '_ansible_dir', return_value=self.runner.Path('/a')), \
                patch.object(self.runner, '_ansible_binary', return_value='ansible-playbook'):
            cmd = self.runner._build_command('inv.yml', params, **files)
        self.assertNotIn('secret', ' '.join(cmd))
        self.assertEqual(cmd[-1], f"@{files['vars_file']}")
        self.assertEqual(os.stat(files['vars_file']).st_mode & 0o777, 0o600)
        with open(files['vars_file'], encoding='utf-8') as handle:
            return self.runner.yaml.safe_load(handle)

    def test_become_password_alone(self):
        self.assertEqual(self._vars(become_password='sudo-secret'),
                         {'ansible_become_password': 'sudo-secret'})

    def test_ssh_and_become_password(self):
        self.assertEqual(
            self._vars(ssh_user='srv01', ssh_password='ssh-secret',
                       become_password='sudo-secret'),
            {'ansible_ssh_pass': 'ssh-secret', 'ansible_become_password': 'sudo-secret',
             'ansible_user': 'srv01'})

    def test_unknown_login_argument_is_refused(self):
        with self.assertRaisesRegex(TypeError, 'ssh_pasword'):
            self.runner.run_playbook('site.yml', ssh_pasword='typo')
