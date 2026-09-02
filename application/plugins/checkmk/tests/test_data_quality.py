"""
Unit tests for the Checkmk Data Quality helpers: CSV hostname parsing and the
pure join that turns monitoring data into the per-host report.
"""
# pylint: disable=missing-function-docstring
import unittest
from unittest.mock import Mock, patch

from application.plugins.checkmk.data_quality import (
    create_internal_cmdb_hosts,
    parse_hostnames_from_csv,
    parse_hostnames_from_text,
    build_report,
    filter_uppercase_hostnames,
    filter_non_fqdn_hostnames,
    apply_domain,
    attach_cmdb_info,
    cmdb_candidates,
    _fetch_monitored_hosts,
    _fetch_checkmk_services,
)


class _FakeCmk:  # pylint: disable=too-few-public-methods
    """Minimal stand-in for CMK2 that returns a canned request response."""
    def __init__(self, response):
        self._response = response
        self.calls = []

    def request(self, url, method='GET', params=None):
        self.calls.append((url, method, params))
        return self._response, {}


class TestParseHostnames(unittest.TestCase):
    """Tests for parse_hostnames_from_csv"""

    def test_empty(self):
        self.assertEqual(parse_hostnames_from_csv(''), [])

    def test_single_column_no_header(self):
        self.assertEqual(
            parse_hostnames_from_csv('host1\nhost2\nhost3'),
            ['host1', 'host2', 'host3'])

    def test_header_named_hostname_is_skipped(self):
        self.assertEqual(
            parse_hostnames_from_csv('hostname\nhost1\nhost2'),
            ['host1', 'host2'])

    def test_header_picks_the_named_column(self):
        text = 'ip,host,site\n1.2.3.4,host1,main\n5.6.7.8,host2,main'
        self.assertEqual(parse_hostnames_from_csv(text), ['host1', 'host2'])

    def test_no_header_uses_first_column(self):
        text = 'host1,1.2.3.4\nhost2,5.6.7.8'
        self.assertEqual(parse_hostnames_from_csv(text), ['host1', 'host2'])

    def test_blank_lines_and_whitespace_ignored(self):
        text = '\n host1 \n\nhost2\n  \n'
        self.assertEqual(parse_hostnames_from_csv(text), ['host1', 'host2'])

    def test_duplicates_removed_order_preserved(self):
        text = 'host1\nhost2\nhost1\nhost3\nhost2'
        self.assertEqual(
            parse_hostnames_from_csv(text),
            ['host1', 'host2', 'host3'])


class TestParseHostnamesText(unittest.TestCase):
    """Tests for parse_hostnames_from_text (pasted textarea input)"""

    def test_empty(self):
        self.assertEqual(parse_hostnames_from_text(''), [])

    def test_one_per_line(self):
        self.assertEqual(
            parse_hostnames_from_text('host1\nhost2\nhost3'),
            ['host1', 'host2', 'host3'])

    def test_comma_and_semicolon_separated(self):
        self.assertEqual(
            parse_hostnames_from_text('host1, host2; host3'),
            ['host1', 'host2', 'host3'])

    def test_mixed_whitespace_and_duplicates(self):
        self.assertEqual(
            parse_hostnames_from_text('  host1 \n\n host2\thost1  '),
            ['host1', 'host2'])


class TestFilterUppercaseHostnames(unittest.TestCase):
    """Tests for the pure uppercase-hostname filter"""

    def test_empty(self):
        self.assertEqual(filter_uppercase_hostnames([]), [])

    def test_only_uppercase_carrying_names_returned(self):
        result = filter_uppercase_hostnames(['host1', 'Host2', 'HOST3'])
        self.assertEqual(
            result,
            [{'name': 'Host2', 'suggested': 'host2'},
             {'name': 'HOST3', 'suggested': 'host3'}])

    def test_sorted_case_insensitively(self):
        names = ['Zeta', 'alpha1', 'Beta', 'ALPHA0']
        # 'alpha1' is all-lowercase and dropped; the rest sort case-insensitively.
        self.assertEqual(
            [h['name'] for h in filter_uppercase_hostnames(names)],
            ['ALPHA0', 'Beta', 'Zeta'])


class TestFilterNonFqdnHostnames(unittest.TestCase):
    """Tests for the pure non-FQDN (no-dot) hostname filter"""

    def test_empty(self):
        self.assertEqual(filter_non_fqdn_hostnames([]), [])

    def test_only_names_without_a_dot_returned(self):
        result = filter_non_fqdn_hostnames(
            ['host1', 'host2.example.com', 'db'])
        self.assertEqual(
            result, [{'name': 'db'}, {'name': 'host1'}])

    def test_sorted_case_insensitively(self):
        self.assertEqual(
            [h['name'] for h in filter_non_fqdn_hostnames(['Zeb', 'alpha', 'Beta'])],
            ['alpha', 'Beta', 'Zeb'])


class TestApplyDomain(unittest.TestCase):
    """Tests for apply_domain"""

    def test_empty_domain_keeps_names(self):
        self.assertEqual(apply_domain(['host1', 'host2'], ''), ['host1', 'host2'])
        self.assertEqual(apply_domain(['host1'], None), ['host1'])

    def test_domain_appended_to_short_names(self):
        self.assertEqual(
            apply_domain(['host1', 'host2'], 'example.com'),
            ['host1.example.com', 'host2.example.com'])

    def test_existing_fqdn_untouched(self):
        self.assertEqual(
            apply_domain(['host1', 'host2.other.net'], 'example.com'),
            ['host1.example.com', 'host2.other.net'])

    def test_leading_dot_and_whitespace_stripped(self):
        self.assertEqual(
            apply_domain(['host1'], '  .example.com '), ['host1.example.com'])


class TestBuildReport(unittest.TestCase):
    """Tests for the pure join in build_report"""

    def test_present_host_with_working_agent(self):
        monitored = {'host1': {'state': 0, 'contact_groups': ['all', 'linux']}}
        services = {'host1': {'state': 0, 'output': 'OK - up'}}
        report = build_report(['host1'], monitored, services)
        entry = report['results'][0]
        self.assertTrue(entry['exists'])
        self.assertEqual(entry['host_state'], 'UP')
        self.assertEqual(entry['agent_state'], 'OK')
        self.assertEqual(entry['contact_groups'], ['all', 'linux'])
        self.assertEqual(report['summary']['found'], 1)
        self.assertEqual(report['summary']['agent_ok'], 1)

    def test_missing_host(self):
        report = build_report(['ghost'], {}, {})
        entry = report['results'][0]
        self.assertFalse(entry['exists'])
        self.assertIsNone(entry['host_state'])
        self.assertIsNone(entry['agent_state'])
        self.assertEqual(report['summary']['missing'], 1)

    def test_present_but_agent_problem(self):
        monitored = {'host1': {'state': 1, 'contact_groups': []}}
        services = {'host1': {'state': 2, 'output': 'CRIT - no data'}}
        report = build_report(['host1'], monitored, services)
        entry = report['results'][0]
        self.assertEqual(entry['host_state'], 'DOWN')
        self.assertEqual(entry['agent_state'], 'CRIT')
        self.assertEqual(entry['agent_output'], 'CRIT - no data')
        self.assertEqual(report['summary']['agent_problem'], 1)

    def test_present_without_checkmk_service(self):
        monitored = {'host1': {'state': 0, 'contact_groups': ['all']}}
        report = build_report(['host1'], monitored, {})
        entry = report['results'][0]
        self.assertTrue(entry['exists'])
        self.assertIsNone(entry['agent_state'])
        self.assertEqual(report['summary']['no_agent'], 1)

    def test_domain_mismatch_input_short_cmk_fqdn(self):
        # Uploaded without a domain, monitored with one.
        monitored = {'web01.example.com': {'state': 0, 'contact_groups': ['all']}}
        services = {'web01.example.com': {'state': 0, 'output': 'OK'}}
        report = build_report(['web01'], monitored, services)
        entry = report['results'][0]
        self.assertEqual(entry['status'], 'domain_mismatch')
        self.assertTrue(entry['exists'])
        self.assertEqual(entry['cmk_name'], 'web01.example.com')
        self.assertEqual(entry['matched_names'], ['web01.example.com'])
        # Monitoring data comes from the actually-matched Checkmk host.
        self.assertEqual(entry['host_state'], 'UP')
        self.assertEqual(entry['agent_state'], 'OK')
        self.assertEqual(report['summary']['domain_mismatch'], 1)
        self.assertEqual(report['summary']['found'], 0)
        self.assertEqual(report['summary']['missing'], 0)

    def test_domain_mismatch_different_domain(self):
        monitored = {'web01.b.de': {'state': 0, 'contact_groups': []}}
        report = build_report(['web01.a.de'], monitored, {})
        entry = report['results'][0]
        self.assertEqual(entry['status'], 'domain_mismatch')
        self.assertEqual(entry['cmk_name'], 'web01.b.de')

    def test_exact_match_wins_over_short_name(self):
        monitored = {
            'web01': {'state': 0, 'contact_groups': ['all']},
            'web01.example.com': {'state': 0, 'contact_groups': ['other']},
        }
        report = build_report(['web01'], monitored, {})
        entry = report['results'][0]
        self.assertEqual(entry['status'], 'found')
        self.assertEqual(entry['cmk_name'], 'web01')
        self.assertEqual(entry['contact_groups'], ['all'])

    def test_summary_totals(self):
        monitored = {
            'a': {'state': 0, 'contact_groups': ['all']},
            'b': {'state': 0, 'contact_groups': ['all']},
        }
        services = {'a': {'state': 0, 'output': ''}}
        report = build_report(['a', 'b', 'c'], monitored, services)
        summary = report['summary']
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['found'], 2)
        self.assertEqual(summary['missing'], 1)
        self.assertEqual(summary['agent_ok'], 1)
        self.assertEqual(summary['no_agent'], 1)


def _report(*rows):
    """Minimal build_report-shaped report for the CMDB enrichment tests."""
    return {'results': list(rows), 'summary': {}}


class TestCmdbCandidates(unittest.TestCase):
    """Tests for cmdb_candidates"""

    def test_given_name_and_checkmk_names_collected(self):
        report = _report(
            {'hostname': 'host1', 'matched_names': []},
            {'hostname': 'host2', 'matched_names': ['host2.example.com']},
        )
        self.assertEqual(
            cmdb_candidates(report),
            {'host1', 'host2', 'host2.example.com'})


class TestAttachCmdbInfo(unittest.TestCase):
    """Tests for attach_cmdb_info"""

    def test_host_with_template(self):
        report = _report({'hostname': 'host1', 'matched_names': []})
        attach_cmdb_info(report, {'host1': ['LinuxTemplate']})
        row = report['results'][0]
        self.assertEqual(row['cmdb_name'], 'host1')
        self.assertEqual(row['cmdb_templates'], ['LinuxTemplate'])
        self.assertEqual(report['summary'],
                         {'in_cmdb': 1, 'with_template': 1, 'without_template': 0})

    def test_host_without_template(self):
        report = _report({'hostname': 'host1', 'matched_names': []})
        attach_cmdb_info(report, {'host1': []})
        self.assertEqual(report['results'][0]['cmdb_name'], 'host1')
        self.assertEqual(report['summary'],
                         {'in_cmdb': 1, 'with_template': 0, 'without_template': 1})

    def test_host_not_in_cmdb(self):
        report = _report({'hostname': 'host1', 'matched_names': []})
        attach_cmdb_info(report, {})
        row = report['results'][0]
        self.assertIsNone(row['cmdb_name'])
        self.assertEqual(row['cmdb_templates'], [])
        self.assertEqual(report['summary'],
                         {'in_cmdb': 0, 'with_template': 0, 'without_template': 0})

    def test_falls_back_to_the_checkmk_name(self):
        # Given without a domain, but the CMDB knows it as the FQDN Checkmk uses
        report = _report(
            {'hostname': 'host1', 'matched_names': ['host1.example.com']})
        attach_cmdb_info(report, {'host1.example.com': ['Tpl']})
        row = report['results'][0]
        self.assertEqual(row['cmdb_name'], 'host1.example.com')
        self.assertEqual(row['cmdb_templates'], ['Tpl'])

    def test_given_name_wins_over_the_checkmk_name(self):
        report = _report(
            {'hostname': 'host1', 'matched_names': ['host1.example.com']})
        attach_cmdb_info(report, {'host1': ['A'], 'host1.example.com': ['B']})
        self.assertEqual(report['results'][0]['cmdb_name'], 'host1')
        self.assertEqual(report['results'][0]['cmdb_templates'], ['A'])


class TestCreateInternalCmdbHosts(unittest.TestCase):
    """application.plugins.checkmk.data_quality.create_internal_cmdb_hosts"""

    def _create(self, template_names):
        hosts = {}

        def get_host(hostname):
            host = Mock()
            host.hostname = hostname
            host.id = None  # not in the CMDB yet
            hosts[hostname] = host
            return host

        with patch('application.models.host.Host') as host_cls, \
             patch('application.plugins.checkmk.data_quality._require_template',
                   side_effect=lambda name, scope=None: f'<{name}>'):
            host_cls.get_host.side_effect = get_host
            result = create_internal_cmdb_hosts(['srv1'], template_names)
        return hosts['srv1'], result

    def test_every_picked_template_lands_on_the_host(self):
        host, result = self._create(['tpl_a', 'tpl_b'])
        self.assertEqual(host.cmdb_templates, ['<tpl_a>', '<tpl_b>'])
        self.assertEqual(result['created'], ['srv1'])
        self.assertEqual(result['templates'], ['tpl_a', 'tpl_b'])

    def test_no_template_leaves_the_host_untouched(self):
        host, result = self._create([])
        # The attribute must not be assigned at all — a host template
        # list set to [] would look like a deliberate reset.
        self.assertNotIn('cmdb_templates', host.__dict__)
        self.assertEqual(result['templates'], [])

    def test_blank_entries_are_dropped(self):
        _host, result = self._create(['tpl_a', '', '  '])
        self.assertEqual(result['templates'], ['tpl_a'])


class TestFetchHelpers(unittest.TestCase):
    """The API glue parses the monitoring REST response shape (value[].extensions)."""

    def test_fetch_monitored_hosts(self):
        response = {'value': [
            {'id': 'host1', 'extensions': {
                'name': 'host1', 'state': 0,
                'contact_groups': ['all', 'linux']}},
            {'id': 'host2', 'extensions': {
                'name': 'host2', 'state': 1, 'contact_groups': []}},
        ]}
        cmk = _FakeCmk(response)
        hosts = _fetch_monitored_hosts(cmk)
        self.assertEqual(hosts['host1'],
                         {'state': 0, 'contact_groups': ['all', 'linux']})
        self.assertEqual(hosts['host2'], {'state': 1, 'contact_groups': []})
        # It asks the monitoring (not the Setup) host endpoint.
        self.assertEqual(cmk.calls[0][0],
                         'domain-types/host/collections/all')

    def test_fetch_checkmk_services(self):
        response = {'value': [
            {'extensions': {
                'host_name': 'host1', 'state': 0, 'plugin_output': 'OK - up'}},
            {'extensions': {
                'host_name': 'host2', 'state': 2, 'plugin_output': 'CRIT'}},
        ]}
        cmk = _FakeCmk(response)
        services = _fetch_checkmk_services(cmk)
        self.assertEqual(services['host1'], {'state': 0, 'output': 'OK - up'})
        self.assertEqual(services['host2'], {'state': 2, 'output': 'CRIT'})
        self.assertEqual(cmk.calls[0][0],
                         'domain-types/service/collections/all')


if __name__ == '__main__':
    unittest.main()
