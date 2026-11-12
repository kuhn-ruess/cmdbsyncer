"""
Export of one topic of a configuration check, and the service discovery
the page starts on the hosts of a topic. No Checkmk needed.
"""
# pylint: disable=missing-function-docstring
import unittest
from datetime import datetime
from unittest import mock

from application.plugins.checkmk.config_checks import discovery
from application.plugins.checkmk.config_checks.base import (
    export_filename, section_csv, topic_report)
from application.plugins.checkmk.config_checks.unhandled import (
    TOPIC_DISCOVERY, UnhandledProblemsCheck, service_findings)


def _service(host, description, state=1):
    return {'host_name': host, 'description': description, 'state': state,
            'plugin_output': 'out; "quoted"', 'check_command': 'check_mk-df',
            'acknowledged': 0, 'scheduled_downtime_depth': 0, 'host_state': 0,
            'host_scheduled_downtime_depth': 0}


def _report():
    findings, _handled, _on_host = service_findings([
        _service('srv01', 'Check_MK Discovery'),
        _service('srv01', 'Filesystem /', state=2)])
    check = UnhandledProblemsCheck()
    return {'name': check.name, 'title': check.title, 'description': '',
            'stats': [], 'sections': check.sections(findings), 'total': 2,
            'warnings': 2}


class TopicExportTest(unittest.TestCase):
    """One topic as its own report and as CSV"""

    def test_discovery_topic_offers_discovery(self):
        self.assertEqual(TOPIC_DISCOVERY.host_action, 'discovery')

    def test_topic_report_keeps_one_section(self):
        report = topic_report(_report(), 'discovery')
        self.assertEqual([s['topic'].key for s in report['sections']], ['discovery'])
        self.assertEqual(report['total'], 1)
        self.assertEqual(report['title'], 'Unhandled problems: Service discovery pending')
        self.assertIsNone(topic_report(_report(), 'nope'))

    def test_csv_opens_in_excel(self):
        csv_text = section_csv(topic_report(_report(), 'by_type')['sections'][0])
        lines = csv_text.split('\r\n')
        self.assertEqual(lines[0], '﻿sep=;')
        self.assertEqual(lines[1], 'Check type;Worst;Count;Services')
        self.assertTrue(lines[2].startswith('df;CRIT;'))
        self.assertIn('srv01 Filesystem /: CRIT: out; ""quoted""', csv_text)

    def test_filename(self):
        self.assertEqual(
            export_filename('cmk test', 'unhandled-discovery', 'csv',
                            datetime(2026, 11, 12)),
            'checkmk-config-checks-cmk_test-unhandled-discovery-2026-11-12.csv')


class _Cmk:  # pylint: disable=too-few-public-methods
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def request(self, url, method='GET', data=None):
        self.calls.append((url, method, data))
        return self.answers.pop(0)


class DiscoveryTest(unittest.TestCase):
    """Start, wait and result of the bulk discovery"""

    def test_options_are_sent_as_chosen(self):
        cmk = _Cmk([({'id': 'bulk_discovery'}, {})])
        job = discovery.start(cmk, ['srv01'], ['monitor_undecided_services'])
        self.assertEqual(job, 'bulk_discovery')
        url, method, body = cmk.calls[0]
        self.assertEqual((url, method), (discovery.START_URL, 'POST'))
        self.assertEqual(body['hostnames'], ['srv01'])
        self.assertEqual(body['options'], {'monitor_undecided_services': True,
                                           'remove_vanished_services': False,
                                           'update_host_labels': False})

    def test_refused_start_raises(self):
        cmk = _Cmk([({}, {'error': 'a bulk discovery is running'})])
        with self.assertRaisesRegex(Exception, 'a bulk discovery is running'):
            discovery.start(cmk, ['srv01'], [])

    def test_wait_polls_until_the_job_ended(self):
        cmk = _Cmk([({'extensions': {'active': True}}, {}),
                    ({'extensions': {'active': False,
                                     'status': {'state': 'finished'}}}, {})])
        sleeps = []
        status = discovery.wait(cmk, 'job', sleep=sleeps.append, clock=lambda: 0)
        self.assertEqual(status['state'], 'finished')
        self.assertEqual(sleeps, [discovery.POLL_SECONDS])

    def test_wait_gives_up(self):
        cmk = _Cmk([({'extensions': {'active': True}}, {})] * 2)
        times = iter([0, discovery.MAX_WAIT_SECONDS + 1])
        with self.assertRaises(TimeoutError):
            discovery.wait(cmk, 'job', sleep=lambda _s: None, clock=lambda: next(times))

    def test_summarize(self):
        failed, lines = discovery.summarize({'state': 'finished', 'log_info': {
            'JobProgressUpdate': ['srv01: 2 new services'], 'JobResult': ['done']}})
        self.assertFalse(failed)
        self.assertEqual(lines, ['srv01: 2 new services', 'done'])
        failed, _lines = discovery.summarize({'state': 'finished', 'log_info': {
            'JobException': ['boom']}})
        self.assertTrue(failed)
        self.assertTrue(discovery.summarize({'state': 'stopped'})[0])

    def test_failed_host_fails_the_finished_job(self):
        status = {'state': 'finished', 'log_info': {'JobProgressUpdate': [
            '[1/1] srv01: discovery failed: [agent] Permission denied',
            'Hosts: 1 total (0 succeeded, 0 skipped, 1 failed)']}}
        self.assertTrue(discovery.summarize(status)[0])
        status['log_info']['JobProgressUpdate'][-1] = \
            'Hosts: 1 total (1 succeeded, 0 skipped, 0 failed)'
        self.assertFalse(discovery.summarize(status)[0])

    def _finish(self, status, activate, activated=True):
        with mock.patch.object(discovery, 'wait', return_value=status), \
                mock.patch.object(discovery, 'app'), \
                mock.patch.object(discovery, 'log') as log, \
                mock.patch('application.plugins.checkmk.cmk2.CMK2'), \
                mock.patch('application.plugins.checkmk.inits.activate_changes',
                           return_value=activated) as activate_changes:
            discovery.finish('cmk', 'job', ['srv01'], ['update_host_labels'],
                             activate, 'admin@example.com')
        return log.log.call_args, activate_changes

    def test_finish_activates_and_logs(self):
        call, activate_changes = self._finish({'state': 'finished'}, True)
        activate_changes.assert_called_once_with('cmk')
        self.assertTrue(call.args[0].endswith('done'))
        details = dict(call.kwargs['details'])
        self.assertEqual(details['options'], 'Update host labels')
        self.assertEqual(details['activate_changes'], 'done')
        self.assertNotIn('error', details)

    def test_failed_job_is_not_activated(self):
        call, activate_changes = self._finish(
            {'state': 'finished', 'log_info': {'JobException': ['boom']}}, True)
        activate_changes.assert_not_called()
        self.assertTrue(call.args[0].endswith('failed'))
        self.assertIn('error', dict(call.kwargs['details']))


if __name__ == '__main__':
    unittest.main()
