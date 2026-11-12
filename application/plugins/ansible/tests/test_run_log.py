"""
The entries of Ansible runs in the log of the Syncer: what is read from
the output of ansible-playbook, and what an ended run writes.
"""
# pylint: disable=missing-function-docstring
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from application.plugins.ansible import run_log

# Output of ansible-playbook 2.17, shortened, with generic host names
FAILED_RUN = '''
PLAY [all] *********************************************************************

TASK [cmk_server_mngmt : Copy Installation File to Servers] ********************
changed: [srv01]
changed: [srv02]

TASK [cmk_server_mngmt : Install Checkmk Version] ******************************
An exception occurred during task execution. To see the full traceback, use -vvv. The error was: SyntaxError: future feature annotations is not defined
fatal: [srv01]: FAILED! => {"changed": false, "module_stderr": "Shared connection to srv01 closed.", "msg": "MODULE FAILURE\\nSee stdout/stderr for the exact error", "rc": 1}
fatal: [srv02]: FAILED! => {"changed": false, "msg": "Gr\\u00f6\\u00dfe passt nicht: \\"quoted\\""}
fatal: [srv03]: UNREACHABLE! => {"changed": false, "msg": "Failed to connect to the host via ssh: Connection timed out", "unreachable": true}

PLAY RECAP *********************************************************************
srv01                      : ok=1    changed=1    unreachable=0    failed=1    skipped=0    rescued=0    ignored=0
srv02                      : ok=1    changed=1    unreachable=0    failed=1    skipped=0    rescued=0    ignored=0
srv03                      : ok=0    changed=0    unreachable=1    failed=0    skipped=0    rescued=0    ignored=0
srv04                      : ok=3    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
'''


def _stats(**values):
    base = {'pk': 'run1', 'playbook': 'cmk_server_mngmt.yml', 'target_host': 'srv01,srv02',
            'mode': 'run', 'source': 'ui', 'triggered_by': 'admin@example.com',
            'status': 'failure', 'exit_code': 2, 'log': FAILED_RUN,
            'started_at': datetime(2026, 11, 12, 18, 0, 0),
            'ended_at': datetime(2026, 11, 12, 18, 3, 25, 500)}
    base.update(values)
    return SimpleNamespace(**base)


class SummarizeTest(unittest.TestCase):
    """What is read from the output"""

    def test_failures_with_task_and_reason(self):
        summary = run_log.summarize(FAILED_RUN)
        self.assertEqual(summary['failures'], [
            ('srv01', 'cmk_server_mngmt : Install Checkmk Version', 'failed',
             'SyntaxError: future feature annotations is not defined'),
            ('srv02', 'cmk_server_mngmt : Install Checkmk Version', 'failed',
             'Größe passt nicht: "quoted"'),
            ('srv03', 'cmk_server_mngmt : Install Checkmk Version', 'unreachable',
             'Failed to connect to the host via ssh: Connection timed out')])

    def test_recap_and_failed_hosts(self):
        summary = run_log.summarize(FAILED_RUN)
        self.assertEqual(summary['recap']['srv04'],
                         'ok=3 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0')
        self.assertEqual(run_log.failed_hosts(summary), ['srv01', 'srv02', 'srv03'])

    def test_ansible_error(self):
        summary = run_log.summarize('ERROR! the playbook: missing.yml could not be found\n')
        self.assertEqual(summary['errors'], ['the playbook: missing.yml could not be found'])


class LogEntryTest(unittest.TestCase):
    """The entries a run writes"""

    def _log(self, function, *args):
        with mock.patch.object(run_log, 'log') as log:
            function(*args)
        return log.log.call_args

    def test_failed_run(self):
        call = self._log(run_log.log_end, _stats(), '\nHint: check the SSH login\n')
        self.assertEqual(call.args[0], 'Ansible: cmk_server_mngmt.yml failure')
        self.assertEqual(call.kwargs['source'], 'Ansible')
        details = call.kwargs['details']
        errors = [value for key, value in details if key == 'error']
        self.assertEqual(errors[0], 'srv01: cmk_server_mngmt : Install Checkmk Version: '
                                    'SyntaxError: future feature annotations is not defined')
        self.assertEqual(len(errors), 3)
        self.assertIn(('duration', '0:03:25'), details)
        self.assertIn(('hint', 'Hint: check the SSH login'), details)
        self.assertIn(('affected_hosts', ['srv01', 'srv02', 'srv03']), details)
        self.assertIn(('host', 'srv04: ok=3 changed=0 unreachable=0 failed=0 '
                               'skipped=0 rescued=0 ignored=0'), details)

    def test_failure_without_ansible_message_gives_the_last_lines(self):
        call = self._log(run_log.log_end, _stats(log='ansible-playbook not found: x', exit_code=-1))
        self.assertIn(('error', 'ansible-playbook not found: x'), call.kwargs['details'])

    def test_success_has_no_error(self):
        call = self._log(run_log.log_end, _stats(status='success', exit_code=0,
                                                 log='PLAY RECAP ***\nsrv04 : ok=3 failed=0\n'))
        self.assertEqual(call.args[0], 'Ansible: cmk_server_mngmt.yml success')
        self.assertFalse([key for key, _value in call.kwargs['details']
                          if key in ('error', 'affected_hosts')])

    def test_start(self):
        call = self._log(run_log.log_start, _stats(status='running'), 'cmk_sites:Prod')
        self.assertEqual(call.args[0], 'Ansible: cmk_server_mngmt.yml started')
        self.assertIn(('inventory', 'cmk_sites:Prod'), call.kwargs['details'])
        self.assertIn(('hosts', 'srv01,srv02'), call.kwargs['details'])

    def test_rule_runs_only_log_the_end(self):
        self.assertIsNone(self._log(run_log.log_start, _stats(source='rule'), 'x'))

    def test_no_extra_vars_in_the_entry(self):
        stats = _stats(extra_vars='secret=hunter2')
        details = self._log(run_log.log_end, stats).kwargs['details']
        self.assertNotIn('hunter2', repr(details))

    def test_a_broken_log_does_not_stop_the_run(self):
        with mock.patch.object(run_log, 'log') as log:
            log.log.side_effect = RuntimeError('db down')
            run_log.log_end(_stats())


if __name__ == '__main__':
    unittest.main()
