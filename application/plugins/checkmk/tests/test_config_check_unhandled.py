"""
Unit tests for the Checkmk configuration check "Unhandled problems": what
counts as unhandled and how the problems are grouped. No Checkmk needed.
"""
# pylint: disable=missing-function-docstring
import unittest

from application.plugins.checkmk.config_checks import get_check
from application.plugins.checkmk.config_checks.unhandled import (
    UnhandledProblemsCheck, check_type, host_findings, service_findings)


def _host(name, state=1, **extra):
    return {'name': name, 'state': state, 'plugin_output': f'{name} down',
            'acknowledged': 0, 'scheduled_downtime_depth': 0, **extra}


def _service(host, description, state=2, command='check_mk-df', **extra):
    return {'host_name': host, 'description': description, 'state': state,
            'plugin_output': 'out', 'check_command': command,
            'acknowledged': 0, 'scheduled_downtime_depth': 0, 'host_state': 0,
            'host_scheduled_downtime_depth': 0, **extra}


class _FakeCmk:  # pylint: disable=too-few-public-methods
    def __init__(self, hosts, services):
        self.answers = {'domain-types/host/collections/all': hosts,
                        'domain-types/service/collections/all': services}

    def request(self, url, method='GET', params=None):  # pylint: disable=unused-argument
        return {'value': [{'extensions': row} for row in self.answers[url]]}, {}


class TestCheckType(unittest.TestCase):
    """check_type"""

    def test_names(self):
        self.assertEqual(check_type('check_mk-df'), 'df')
        self.assertEqual(check_type('check_mk_active-http!--url x'),
                         'http (active check)')
        self.assertEqual(check_type('check-mk-custom!foo'), 'check-mk-custom')
        self.assertEqual(check_type(''), 'unknown')


class TestHosts(unittest.TestCase):
    """host_findings"""

    def test_handled_hosts_skipped(self):
        findings, handled = host_findings([
            _host('srv01'), _host('srv02', state=2),
            _host('srv03', acknowledged=1),
            _host('srv04', scheduled_downtime_depth=1),
            _host('srv05', state=0)])
        self.assertEqual(handled, 2)
        self.assertEqual([(f.values['host'], f.values['state']) for f in findings],
                         [('srv02', 'UNREACHABLE'), ('srv01', 'DOWN')])


class TestServices(unittest.TestCase):
    """service_findings"""

    def test_handled_and_host_problems_skipped(self):
        findings, handled, on_host = service_findings([
            _service('srv01', 'Filesystem /', acknowledged=1),
            _service('srv01', 'Filesystem /var', scheduled_downtime_depth=1),
            _service('srv01', 'Filesystem /opt', host_scheduled_downtime_depth=1),
            _service('srv02', 'Filesystem /', host_state=1),
            _service('srv03', 'Filesystem /', state=0)])
        self.assertEqual((findings, handled, on_host), ([], 3, 1))

    def test_agent_and_discovery_by_host(self):
        findings, _handled, _on_host = service_findings([
            _service('srv01', 'Check_MK', command='check-mk'),
            _service('srv02', 'Check_MK Discovery', state=1,
                     command='check-mk-inventory')])
        self.assertEqual([(f.topic, f.values['host'], f.values['state'])
                          for f in findings],
                         [('agent', 'srv01', 'CRIT'),
                          ('discovery', 'srv02', 'WARN')])

    def test_grouped_by_type_worst_first(self):
        findings, _handled, _on_host = service_findings([
            _service('srv01', 'CPU load', state=1, command='check_mk-cpu_loads'),
            _service('srv02', 'CPU load', state=1, command='check_mk-cpu_loads'),
            _service('srv01', 'Filesystem /', state=1),
            _service('srv02', 'Filesystem /'),
            _service('srv01', 'HTTP www', state=3,
                     command='check_mk_active-httpv2!x')])
        self.assertEqual([(f.values['check_type'], f.values['state'])
                          for f in findings],
                         [('df', 'CRIT'), ('httpv2 (active check)', 'UNKNOWN'),
                          ('cpu_loads', 'WARN')])
        df = findings[0]
        self.assertEqual(df.values['summary'], '2 (1 CRIT, 1 WARN) on 2 hosts')
        self.assertEqual([(i['service'], i['rule'], i['detail'])
                          for i in df.values['services']],
                         [('srv02', 'Filesystem /', 'CRIT: out'),
                          ('srv01', 'Filesystem /', 'WARN: out')])


class TestCheck(unittest.TestCase):
    """UnhandledProblemsCheck.run"""

    def test_registered_and_run(self):
        self.assertIs(get_check('unhandled'), UnhandledProblemsCheck)
        cmk = _FakeCmk([_host('srv01'), _host('srv02', acknowledged=1)],
                       [_service('srv01', 'Filesystem /', host_state=1),
                        _service('srv03', 'Filesystem /')])
        report = UnhandledProblemsCheck().run(cmk, 'cmk01')
        self.assertEqual(report['total'], 2)
        self.assertEqual([len(s['findings']) for s in report['sections']],
                         [1, 0, 0, 1])
        self.assertIn(('Services on hosts not UP', 1), report['stats'])


if __name__ == '__main__':
    unittest.main()
