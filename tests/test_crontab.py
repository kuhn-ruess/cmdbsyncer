"""
The crontab entry `cmdbsyncer cron install` writes
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import subprocess
import unittest
from datetime import datetime, timedelta
from unittest import mock

from application.helpers import crontab


class CronLineTest(unittest.TestCase):

    def test_the_line_changes_into_the_config_dir(self):
        line = crontab.cron_line(5, '/opt/cmdbsyncer', '/opt/cmdbsyncer/venv/bin/cmdbsyncer',
                                 '/opt/cmdbsyncer/venv/bin/python')
        self.assertEqual(line, "*/5 * * * * cd /opt/cmdbsyncer && "
                               "/opt/cmdbsyncer/venv/bin/python "
                               "/opt/cmdbsyncer/venv/bin/cmdbsyncer cron run_jobs > /dev/null")

    def test_paths_with_spaces_are_quoted(self):
        line = crontab.cron_line(10, '/opt/my syncer', '/opt/my syncer/venv/bin/cmdbsyncer',
                                 '/opt/my syncer/venv/bin/python')
        self.assertIn("cd '/opt/my syncer' && '/opt/my syncer/venv/bin/python' "
                      "'/opt/my syncer/venv/bin/cmdbsyncer'", line)
        self.assertTrue(line.startswith('*/10 '))

    def test_the_started_binary_is_used(self):
        with mock.patch.object(crontab.sys, 'argv', ['/opt/x/venv/bin/cmdbsyncer', 'cron']):
            self.assertEqual(crontab.syncer_binary(), '/opt/x/venv/bin/cmdbsyncer')

    def test_otherwise_the_one_next_to_python(self):
        with mock.patch.object(crontab.sys, 'argv', ['-m']), \
                mock.patch.object(crontab.sys, 'executable', '/opt/x/venv/bin/python'):
            self.assertEqual(crontab.syncer_binary(), '/opt/x/venv/bin/cmdbsyncer')


class CrontabContentTest(unittest.TestCase):

    def test_an_existing_entry_is_found(self):
        text = "MAILTO=ops@example.com\n*/5 * * * * cd /srv && ./cmdbsyncer cron run_jobs\n"
        self.assertEqual(crontab.existing_entry(text),
                         "*/5 * * * * cd /srv && ./cmdbsyncer cron run_jobs")

    def test_a_commented_entry_does_not_count(self):
        self.assertIsNone(crontab.existing_entry("# */5 * * * * cmdbsyncer cron run_jobs\n"))

    def test_other_lines_are_kept(self):
        text = crontab.with_entry("0 3 * * * /usr/local/bin/backup", "LINE")
        self.assertEqual(text, f"0 3 * * * /usr/local/bin/backup\n{crontab.MARKER}\nLINE\n")

    def test_an_empty_crontab_gets_the_entry(self):
        self.assertEqual(crontab.with_entry('', 'LINE'), f"{crontab.MARKER}\nLINE\n")


def _done(returncode=0, stdout='', stderr=''):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


@mock.patch.object(crontab.shutil, 'which', return_value='/usr/bin/crontab')
class CrontabCommandTest(unittest.TestCase):

    def test_no_crontab_yet_reads_as_empty(self, _which):
        with mock.patch.object(crontab.subprocess, 'run',
                               return_value=_done(1, stderr='no crontab for cmdbsyncer')):
            self.assertEqual(crontab.read_crontab(), '')

    def test_another_read_error_is_reported(self, _which):
        with mock.patch.object(crontab.subprocess, 'run',
                               return_value=_done(1, stderr='not allowed to use crontab')):
            with self.assertRaisesRegex(crontab.CrontabError, 'not allowed'):
                crontab.read_crontab()

    def test_writing_passes_the_whole_crontab(self, _which):
        with mock.patch.object(crontab.subprocess, 'run', return_value=_done()) as run:
            crontab.write_crontab('NEW\n')
        self.assertEqual(run.call_args.args[0], ['/usr/bin/crontab', '-'])
        self.assertEqual(run.call_args.kwargs['input'], 'NEW\n')

    def test_without_cron_the_reason_is_named(self, which):
        which.return_value = None
        with self.assertRaisesRegex(crontab.CrontabError, 'install cron'):
            crontab.read_crontab()


class HeartbeatTest(unittest.TestCase):
    NOW = datetime(2026, 11, 18, 12, 0)

    def test_never_run_is_missing(self):
        self.assertTrue(crontab.missing_heartbeat(None, self.NOW))

    def test_a_recent_pass_is_fine(self):
        self.assertFalse(crontab.missing_heartbeat(self.NOW - timedelta(minutes=59), self.NOW))

    def test_an_old_pass_is_missing(self):
        self.assertTrue(crontab.missing_heartbeat(self.NOW - timedelta(minutes=61), self.NOW))


if __name__ == '__main__':
    unittest.main()
