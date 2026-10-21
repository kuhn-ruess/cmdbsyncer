"""
Unit tests for the Checkmk configuration checks: the registry, the rule
parsing and the check_httpv2 duplicate and mergeable detection. No Checkmk
needed, the REST answers are canned.
"""
# pylint: disable=missing-function-docstring
import json
import unittest
from datetime import datetime

from application.plugins.checkmk.config_checks import (
    ConfigCheck, Finding, describe_conditions, get_check, get_checks,
    register_check)
from application.plugins.checkmk.config_checks.base import parse_rule
from application.plugins.checkmk.config_checks.httpv2 import (
    HttpV2Check, analyze_endpoints, collect_endpoints, endpoint_role,
    failing_findings, fetch_failing_services, legacy_findings, migrated_ids,
    normalize_url)

DAY = 86400
CERT = ('validate', ('fixed', (40.0 * DAY, 20.0 * DAY)))
NO_CERT = ('no_validation', None)


def _endpoint(url, name, settings=None):
    endpoint = {'service_name': {'prefix': 'auto', 'name': name}, 'url': url}
    if settings is not None:
        endpoint['individual_settings'] = settings
    return endpoint


def _rule(rule_id, endpoints, standard=None, *, folder='/', conditions=None):
    return {
        'id': rule_id, 'folder': folder, 'description': f'rule {rule_id}',
        'disabled': False,
        'conditions': conditions if conditions is not None else {
            'host_name': {'match_on': ['srv01'], 'operator': 'one_of'}},
        'value': {'endpoints': endpoints,
                  'standard_settings': standard or {}},
    }


def _website(rule_id, url='https://www.example.com', **kwargs):
    return _rule(rule_id, [_endpoint(url, 'Website')],
                 standard={'cert': NO_CERT,
                           'server_response': {'expected': [200]}}, **kwargs)


def _certificate(rule_id, url='https://www.example.com', **kwargs):
    return _rule(rule_id, [_endpoint(url, 'Certificate')],
                 standard={'cert': CERT}, **kwargs)


def _findings(rules):
    endpoints, _skipped = collect_endpoints(rules)
    return analyze_endpoints(endpoints)


class _FakeCmk:  # pylint: disable=too-few-public-methods
    """Answers rule collection requests per ruleset."""
    def __init__(self, by_ruleset):
        self.by_ruleset = by_ruleset
        self.calls = []

    def request(self, url, method='GET', params=None):
        self.calls.append((url, method, params))
        if url == 'domain-types/service/collections/all':
            return {'value': self.by_ruleset.get('services', [])}, {}
        ruleset = url.split('ruleset_name=', 1)[1]
        return {'value': self.by_ruleset.get(ruleset, [])}, {}


class TestRegistry(unittest.TestCase):
    """register_check / get_checks"""

    def test_httpv2_registered(self):
        self.assertIs(get_check('httpv2'), HttpV2Check)
        self.assertIn(HttpV2Check, get_checks())

    def test_unknown_check(self):
        self.assertIsNone(get_check('nope'))

    def test_double_registration_rejected(self):
        class Again(ConfigCheck):  # pylint: disable=too-few-public-methods
            """Same name as the built-in"""
            name = 'httpv2'

            def analyze(self, cmk):
                return [], []
        with self.assertRaises(ValueError):
            register_check(Again)

    def test_nameless_check_rejected(self):
        class Nameless(ConfigCheck):  # pylint: disable=too-few-public-methods
            """No name"""

            def analyze(self, cmk):
                return [], []
        with self.assertRaises(ValueError):
            register_check(Nameless)


class TestParseRule(unittest.TestCase):
    """parse_rule / describe_conditions"""

    def test_parses_value_raw_and_folder(self):
        rule = parse_rule({'id': 'r1', 'extensions': {
            'folder': '~servers~web',
            'value_raw': "{'endpoints': [], 'standard_settings': {'cert': "
                         "('no_validation', None)}}",
            'properties': {'description': 'Web', 'disabled': True},
            'conditions': {'host_tags': []}}})
        self.assertEqual(rule['folder'], '/servers/web')
        self.assertTrue(rule['disabled'])
        self.assertEqual(rule['value']['standard_settings']['cert'], NO_CERT)

    def test_unparsable_value(self):
        rule = parse_rule({'id': 'r1', 'extensions': {'value_raw': '{broken'}})
        self.assertIsNone(rule['value'])

    def test_describe_conditions(self):
        self.assertEqual(describe_conditions({'host_tags': []}), 'all hosts')
        text = describe_conditions({
            'host_name': {'match_on': ['srv01', 'srv02'], 'operator': 'one_of'},
            'host_tags': [{'key': 'criticality', 'operator': 'is', 'value': 'prod'}],
            'host_label_groups': [{'operator': 'and', 'label_group': [
                {'operator': 'and', 'label': 'app:web'}]}],
        })
        self.assertEqual(text, 'host labels app:web; host name srv01, srv02; '
                               'tag criticality is prod')


class TestNormalizeUrl(unittest.TestCase):
    """normalize_url"""

    def test_default_port_case_and_path(self):
        self.assertEqual(normalize_url('HTTPS://WWW.Example.com:443'),
                         'https://www.example.com/')
        self.assertEqual(normalize_url('http://www.example.com:80/a'),
                         'http://www.example.com/a')

    def test_other_port_kept(self):
        self.assertEqual(normalize_url('https://www.example.com:8443/'),
                         'https://www.example.com:8443/')

    def test_macro_url(self):
        self.assertEqual(normalize_url('https://$HOSTNAME$'),
                         normalize_url('https://$HOSTNAME$/'))


class TestEndpointRole(unittest.TestCase):
    """endpoint_role"""

    def test_roles(self):
        self.assertEqual(endpoint_role({'cert': CERT}), 'certificate')
        self.assertEqual(endpoint_role(
            {'cert': CERT, 'document': {'document_body': 'ignore'}}),
            'certificate')
        self.assertEqual(endpoint_role({'cert': NO_CERT}), 'website')
        self.assertEqual(endpoint_role({}), 'website')
        self.assertEqual(endpoint_role(
            {'cert': ('validate', ('no_levels', None))}), 'website')
        self.assertEqual(endpoint_role(
            {'cert': CERT, 'server_response': {'expected': [200]}}),
            'website + certificate')


class TestHttpV2Detection(unittest.TestCase):
    """collect_endpoints / analyze_endpoints"""

    def test_website_and_certificate_are_mergeable(self):
        findings = _findings([_website('r1'), _certificate('r2')])
        self.assertEqual([f.topic for f in findings], ['mergeable'])
        finding = findings[0]
        values = finding.values
        self.assertEqual(values['url'], 'https://www.example.com')
        self.assertEqual(values['conditions'], 'host name srv01')
        self.assertEqual([i['rule_id'] for i in values['website']], ['r1'])
        self.assertEqual([i['rule_id'] for i in values['certificate']], ['r2'])
        self.assertIn('warn 40 / crit 20 days', values['certificate'][0]['detail'])
        self.assertIn("'HTTPS Website'", values['recommendation'])

    def test_url_spelling_does_not_matter(self):
        findings = _findings([
            _website('r1', url='https://www.example.com/'),
            _certificate('r2', url='https://WWW.EXAMPLE.COM:443')])
        self.assertEqual([f.topic for f in findings], ['mergeable'])

    def test_combined_check_makes_certificate_check_redundant(self):
        combined = _rule('r1', [_endpoint('https://www.example.com', 'Web')],
                         standard={'cert': CERT,
                                   'server_response': {'expected': [200]}})
        findings = _findings([combined, _certificate('r2')])
        self.assertEqual([f.topic for f in findings], ['mergeable'])
        self.assertIn('already checks the certificate',
                      findings[0].values['recommendation'])

    def test_differing_settings_named_without_values(self):
        cert = _certificate('r2')
        cert['value']['standard_settings']['connection'] = {
            'auth': ('user_auth', {'user': 'u', 'password': 'secret'})}
        findings = _findings([_website('r1'), cert])
        detail = findings[0].values['certificate'][0]['detail']
        self.assertIn('other settings differ: connection', detail)
        self.assertNotIn('secret', detail)

    def test_exact_duplicate(self):
        findings = _findings([_website('r1'), _website('r2')])
        self.assertEqual([f.topic for f in findings], ['duplicate'])
        self.assertEqual(len(findings[0].values['checks']), 2)

    def test_duplicate_endpoints_inside_one_rule(self):
        rule = _rule('r1', [_endpoint('https://www.example.com', 'A'),
                            _endpoint('https://www.example.com', 'B')],
                     standard={'cert': NO_CERT})
        findings = _findings([rule])
        self.assertEqual([f.topic for f in findings], ['duplicate'])
        self.assertEqual([i['service'] for i in findings[0].values['checks']],
                         ['HTTPS A', 'HTTPS B'])

    def test_individual_settings_win(self):
        rule = _rule('r1', [
            _endpoint('https://www.example.com', 'Web'),
            _endpoint('https://www.example.com', 'Cert', {'cert': CERT})],
            standard={'cert': NO_CERT, 'server_response': {'expected': [200]}})
        findings = _findings([rule])
        # The certificate endpoint still inherits server_response, so it
        # checks the page as well: website + certificate next to website.
        self.assertEqual([f.topic for f in findings], ['same_url'])

    def test_duplicate_and_merge_together(self):
        findings = _findings([_website('r1'), _website('r2'),
                              _certificate('r3')])
        self.assertEqual(sorted(f.topic for f in findings),
                         ['duplicate', 'mergeable'])

    def test_different_content_checks_are_information(self):
        other = _website('r2')
        other['value']['standard_settings']['server_response'] = {
            'expected': [301]}
        findings = _findings([_website('r1'), other])
        self.assertEqual([f.topic for f in findings], ['same_url'])

    def test_no_finding_when_scope_differs(self):
        for other in (
                _certificate('r2', folder='/other'),
                _certificate('r2', conditions={
                    'host_name': {'match_on': ['srv02'], 'operator': 'one_of'}}),
                _certificate('r2', url='https://shop.example.com'),
        ):
            self.assertEqual(_findings([_website('r1'), other]), [])

    def test_server_setting_separates_targets(self):
        cert = _certificate('r2')
        cert['value']['standard_settings']['server'] = '192.0.2.10'
        self.assertEqual(_findings([_website('r1'), cert]), [])

    def test_empty_conditions_compare_equal(self):
        findings = _findings([_website('r1', conditions={}),
                              _certificate('r2', conditions={'host_tags': []})])
        self.assertEqual([f.topic for f in findings], ['mergeable'])
        self.assertEqual(findings[0].values['conditions'], 'all hosts')

    def test_disabled_and_unreadable_rules_skipped(self):
        broken = _website('r3')
        broken['value'] = None
        disabled = _certificate('r2')
        disabled['disabled'] = True
        endpoints, skipped = collect_endpoints(
            [_website('r1'), disabled, broken])
        self.assertEqual(len(endpoints), 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(analyze_endpoints(endpoints), [])


class TestLegacyRules(unittest.TestCase):
    """legacy_findings"""

    def test_enabled_legacy_rules_reported(self):
        rules = [
            {'id': 'l1', 'folder': '/', 'description': '', 'disabled': False,
             'conditions': {}, 'value': {'name': 'Shop', 'host': {}}},
            {'id': 'l2', 'folder': '/', 'description': '', 'disabled': True,
             'conditions': {}, 'value': {'name': 'Old'}},
        ]
        findings = legacy_findings(rules)
        self.assertEqual([(f.topic, f.values['name']) for f in findings],
                         [('not_migrated', 'Shop')])

    def test_migrated_but_not_finalized(self):
        new_rule = _website('r1')
        new_rule['comment'] = 'Migrated from v1: l1'
        self.assertEqual(migrated_ids([new_rule, _website('r2')]), {'l1'})
        old = {'id': 'l1', 'folder': '/', 'description': '',
               'disabled': False, 'conditions': {}, 'value': {'name': 'Shop'}}
        findings = legacy_findings([old], migrated_ids([new_rule]))
        self.assertEqual(findings[0].topic, 'not_finalized')


def _service(host, description, state, output='', command='httpv2'):
    return {'host_name': host, 'description': description, 'state': state,
            'output': output, 'legacy': command != 'httpv2'}


class TestSections(unittest.TestCase):
    """ConfigCheck.sections and the topic declarations"""

    def test_every_topic_has_a_section_in_order(self):
        check = HttpV2Check()
        sections = check.sections([Finding('duplicate', {'url': 'x'})])
        self.assertEqual([section['topic'].key for section in sections],
                         [topic.key for topic in check.topics])
        self.assertEqual([len(section['findings']) for section in sections],
                         [0, 1, 0, 0, 0, 0])

    def test_undeclared_topic_rejected(self):
        with self.assertRaises(ValueError):
            HttpV2Check().sections([Finding('nope')])

    def test_columns_match_finding_values(self):
        rules = [_website('r1'), _website('r2'), _certificate('r3')]
        endpoints, _skipped = collect_endpoints(rules)
        findings = analyze_endpoints(endpoints) + failing_findings(
            [_service('srv01', 'HTTPS Website', 2)], endpoints)
        topics = {topic.key: topic for topic in HttpV2Check.topics}
        for finding in findings:
            keys = {column.key for column in topics[finding.topic].columns}
            self.assertEqual(keys, set(finding.values), finding.topic)


class TestFailingServices(unittest.TestCase):
    """fetch_failing_services / failing_findings"""

    def test_fetch_query_and_parse(self):
        cmk = _FakeCmk({'services': [{'extensions': {
            'host_name': 'srv01', 'description': 'HTTPS Website', 'state': 2,
            'plugin_output': 'Connection refused',
            'check_command': 'check_mk_active-httpv2!--url https://x'}}, {
            'extensions': {
                'host_name': 'srv02', 'description': 'HTTP Shop', 'state': 1,
                'plugin_output': '', 'check_command': 'check_mk_active-http!-I x'}}]})
        services = fetch_failing_services(cmk)
        url, method, params = cmk.calls[0]
        self.assertEqual((url, method), ('domain-types/service/collections/all', 'GET'))
        query = json.loads(params['query'])
        self.assertIn({'op': '!=', 'left': 'state', 'right': '0'}, query['expr'])
        self.assertIn('check_command', [e['left'] for e in query['expr']])
        self.assertEqual([(s['host_name'], s['legacy']) for s in services],
                         [('srv01', False), ('srv02', True)])

    def test_findings_traced_to_rules_worst_first(self):
        endpoints, _skipped = collect_endpoints([_website('r1')])
        legacy = [{'id': 'l1', 'folder': '/', 'description': 'old',
                   'disabled': False, 'conditions': {},
                   'value': {'name': 'Shop'}}]
        findings = failing_findings([
            _service('srv02', 'HTTP Shop', 1, 'slow', command='http'),
            _service('srv01', 'HTTPS Website', 2, 'Connection refused'),
            _service('srv03', 'HTTPS Other', 3),
            _service('srv04', 'HTTPS Website', 0),
        ], endpoints, legacy)
        self.assertEqual([f.values['state'] for f in findings],
                         ['UNKNOWN', 'CRIT', 'WARN'])
        unknown, crit, warn = findings[0], findings[1], findings[2]
        self.assertEqual((crit.values['host'], crit.values['service']),
                         ('srv01', 'HTTPS Website'))
        self.assertEqual(crit.values['output'], 'Connection refused')
        self.assertEqual(crit.values['rules'][0]['rule_id'], 'r1')
        self.assertEqual(warn.values['rules'][0]['rule_id'], 'l1')
        self.assertNotIn('rule_id', unknown.values['rules'][0])


class TestHttpV2Run(unittest.TestCase):
    """HttpV2Check.run with a canned REST answer"""

    @staticmethod
    def api_rule(rule_id, value_raw):
        """One rule as the REST API returns it."""
        return {'id': rule_id, 'extensions': {
            'folder': '/', 'value_raw': value_raw,
            'properties': {'description': rule_id},
            'conditions': {'host_name': {'match_on': ['srv01'],
                                         'operator': 'one_of'}}}}

    def test_run(self):
        cmk = _FakeCmk({
            'active_checks:httpv2': [
                self.api_rule('r1', repr(_website('x')['value'])),
                self.api_rule('r2', repr(_certificate('x')['value'])),
            ],
            'active_checks:http': [
                self.api_rule('l1', "{'name': 'Shop', 'host': {}}"),
            ],
        })
        report = HttpV2Check().run(cmk, 'cmk-test')
        self.assertEqual([c[0] for c in cmk.calls], [
            'domain-types/rule/collections/all?ruleset_name=active_checks:httpv2',
            'domain-types/rule/collections/all?ruleset_name=active_checks:http',
            'domain-types/service/collections/all',
        ])
        self.assertTrue(all(call[1] == 'GET' for call in cmk.calls))
        counts = {section['topic'].key: len(section['findings'])
                  for section in report['sections']}
        self.assertEqual(counts, {'failing': 0, 'duplicate': 0, 'mergeable': 1,
                                  'same_url': 0, 'not_finalized': 0,
                                  'not_migrated': 1})
        self.assertEqual((report['total'], report['warnings']), (2, 2))
        self.assertEqual(dict(report['stats'])['Endpoints compared'], 2)
        self.assertEqual(report['account'], 'cmk-test')


if __name__ == '__main__':
    unittest.main()


try:
    from application.plugins.checkmk.config_checks import pdf as report_pdf
except ImportError:  # fpdf2 is optional (cmdbsyncer[extras])
    report_pdf = None


@unittest.skipIf(report_pdf is None, "fpdf2 (cmdbsyncer[extras]) is not installed")
class TestPdfReport(unittest.TestCase):
    """config_checks.pdf"""

    def test_render_pdf(self):
        cmk = _FakeCmk({
            'active_checks:httpv2': [
                TestHttpV2Run.api_rule('r1', repr(_website('x')['value'])),
                TestHttpV2Run.api_rule('r2', repr(_certificate('x')['value'])),
            ],
            'services': [{'extensions': {
                'host_name': 'srv01', 'description': 'HTTPS Website',
                'state': 2, 'plugin_output': 'Timeout … über',
                'check_command': 'check_mk_active-httpv2!x'}}],
        })
        data = report_pdf.render_pdf([HttpV2Check().run(cmk, 'cmk-test')],
                                     'cmk-test', brand_color='#000')
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertTrue(data.rstrip().endswith(b'%%EOF'))

    def test_helpers(self):
        self.assertEqual(report_pdf.latin1('a … — ü 中'),
                         'a ... - ü ?')
        self.assertEqual(report_pdf.parse_color('#000'), (0, 0, 0))
        self.assertEqual(report_pdf.parse_color('#2c3e50'), (44, 62, 80))
        self.assertEqual(report_pdf.parse_color('red'), report_pdf.DEFAULT_BRAND)
        self.assertEqual(
            report_pdf.pdf_filename('cmk test/../x', datetime(2026, 1, 2)),
            'checkmk-config-checks-cmk_test_.._x-2026-01-02.pdf')
