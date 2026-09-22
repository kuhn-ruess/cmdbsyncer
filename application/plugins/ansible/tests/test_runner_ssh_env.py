"""
The playbook runner has to work under a web user without a writable home.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
import os
import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock

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
