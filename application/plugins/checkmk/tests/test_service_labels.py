"""
Unit tests for the Checkmk Service Labels export
"""
# pylint: disable=missing-function-docstring,protected-access
import ast
import itertools
import re
import unittest
from unittest.mock import MagicMock, patch

from application.plugins.checkmk.inventorize import PER_SERVICE_LABELS_ATTRIBUTE
from application.plugins.checkmk.service_labels import (
    CheckmkServiceLabelSync,
    SERVICE_LABEL_RULESET,
    checkmk_service_regex,
    exact_service_regex,
)
from application.plugins.checkmk.rules import ServiceLabelRule
from application.plugins.checkmk.cmk_rules import CheckmkRuleSync
from tests import base_mock_init, real_render_jinja


def make_sync(cls=CheckmkServiceLabelSync):
    with patch('application.plugins.checkmk.cmk_rules.CMK2.__init__',
               lambda self_param, account=False, **_kwargs: base_mock_init(
                   self_param, rulsets_by_type={}, dry_run=False, account_id='7')):
        return cls()


def outcome(service_pattern, label_name, label_value, **extra):
    return {'service_pattern': service_pattern, 'label_name': label_name,
            'label_value': label_value, **extra}


def host_attributes(hostname, entries, **more):
    return {'HOSTNAME': hostname, PER_SERVICE_LABELS_ATTRIBUTE: entries, **more}


def service(name, **labels):
    return {'service': name, 'labels': labels}


# A repair as it is entered in the GUI: without the label it renders empty.
REPAIR = ("{% set l = LABELS.raw|default('') %}"
          "{% if l.startswith('e-') %}{{ HOSTNAME }}-{{ l[2:] }}{% else %}{{ l }}{% endif %}")


class RenderedTest(unittest.TestCase):
    """Runs the templates through real Jinja"""

    def setUp(self):
        patcher = patch('application.plugins.checkmk.service_labels.render_jinja',
                        real_render_jinja)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sync = make_sync()
        self.sync.log_error = MagicMock()


class TestLabelsOfService(RenderedTest):
    """What the outcomes set on a single service"""

    def labels(self, entry, *outcomes, **attributes):
        found = self.sync.labels_of_service(
            entry, list(outcomes), {'HOSTNAME': 'srv01', **attributes})
        return {name: value for name, (value, _folder) in found.items()}

    def test_pattern_decides(self):
        rule = outcome(r'^Port \d$', 'kind', 'port')
        self.assertEqual(self.labels(service('Port 1'), rule), {'kind': 'port'})
        self.assertEqual(self.labels(service('Fan 1'), rule), {})

    def test_template_context(self):
        rule = outcome(r'^(Port) (\d+)$', 'x',
                       '{{ HOSTNAME }}/{{ SERVICE }}/{{ MATCH[0] }}/{{ MATCH[2] }}/'
                       '{{ LABELS.raw }}/{{ site }}')
        self.assertEqual(self.labels(service('Port 12', raw='r'), rule, site='s1'),
                         {'x': 'srv01/Port 12/Port 12/12/r/s1'})

    def test_service_without_the_label_renders_empty(self):
        rule = outcome('^Port', 'x', REPAIR)
        for entry in (service('Port 1'), service('Port 1', other='o'),
                      service('Port 1', raw='')):
            self.assertEqual(self.labels(entry, rule), {})
        self.assertEqual(self.labels(service('Port 1', raw='e-a'), rule), {'x': 'srv01-a'})
        self.sync.log_error.assert_not_called()

    def test_service_without_labels_still_gets_one(self):
        rule = outcome('^Port', 'x', '{{ LABELS.raw or HOSTNAME }}')
        self.assertEqual(self.labels(service('Port 1'), rule), {'x': 'srv01'})

    def test_first_value_wins_and_empty_falls_through(self):
        self.assertEqual(self.labels(service('Port 1'),
                                     outcome('^Port', 'x', ''),
                                     outcome('^Port', 'x', 'second'),
                                     outcome('^Port', 'x', 'third')),
                         {'x': 'second'})

    def test_broken_pattern_and_template_only_cost_themselves(self):
        self.assertEqual(self.labels(service('Port 1'),
                                     outcome('(', 'x', 'a'),
                                     outcome('^Port', 'y', '{{ LABELS.nope.split("-") }}'),
                                     outcome('^Port', 'z', 'fine')),
                         {'z': 'fine'})
        self.assertEqual(self.sync.log_error.call_count, 2)

    def test_value_checkmk_already_shows_is_still_set(self):
        # Must not be left out because Checkmk already shows that value: the
        # value is only there because of this very rule.
        self.assertEqual(self.labels(service('Port 1', x='same'),
                                     outcome('^Port', 'x', 'same')), {'x': 'same'})


class TestDebugHost(RenderedTest):
    """The output of the rules on the debug page"""

    def rows(self, outcomes, entries, **more):
        """``[(service or regex, label, value)]``"""
        attributes = {'all': host_attributes('srv01', entries, **more)}
        return [(row['service'], row['name'], row['value'])
                for row in self.sync.debug_host(outcomes, MagicMock(is_object=False), attributes)]

    def test_no_service_data_renders_from_the_host(self):
        outcomes = [outcome('^Port (\\d)', 'host', '{{ HOSTNAME }}'),
                    outcome('^Port (\\d)', 'label', "{{ LABELS.raw|default('') }}"),
                    outcome('^Port (\\d)', 'match', '{{ MATCH[1] }}'),
                    outcome('^Fan', 'site', '{{ site }}-{{ SERVICE }}')]
        for entries in (None, []):
            self.assertEqual(self.rows(outcomes, entries, site='s1'), [
                ('^Port (\\d)', 'host', 'srv01'),
                ('^Fan', 'site', 's1-')])

    def test_one_row_per_known_service(self):
        outcomes = [outcome('^Port (\\d)', 'host', '{{ HOSTNAME }}'),
                    outcome('^Port (\\d)', 'label', "{{ LABELS.raw|default('') }}"),
                    outcome('^Port (\\d)', 'match', '{{ MATCH[1] }}')]
        self.assertEqual(self.rows(outcomes, [service('Port 1', raw='e-a'), service('Port 2')]), [
            ('Port 1', 'host', 'srv01'), ('Port 1', 'label', 'e-a'), ('Port 1', 'match', '1'),
            ('Port 2', 'host', 'srv01'), ('Port 2', 'match', '2')])

    def test_regex_without_a_known_service_next_to_one_with(self):
        self.assertEqual(self.rows([outcome('^Fan', 'x', '{{ HOSTNAME }}'),
                                    outcome('^Port', 'y', 'set')], [service('Port 1')]),
                         [('^Fan', 'x', 'srv01'), ('Port 1', 'y', 'set')])

    def test_first_value_wins_as_in_the_export(self):
        outcomes = [outcome('^Port', 'x', 'first'), outcome('^Port', 'x', 'second')]
        self.assertEqual(self.rows(outcomes, [service('Port 1')]), [('Port 1', 'x', 'first')])
        self.assertEqual(self.rows(outcomes, None), [('^Port', 'x', 'first')])

    def test_empty_value_is_not_sent_and_leaves_the_label_to_the_next_rule(self):
        outcomes = [outcome('^Port', 'x', ''), outcome('^Port', 'x', 'second')]
        self.assertEqual(self.rows(outcomes, [service('Port 1')]), [('Port 1', 'x', 'second')])
        self.assertEqual(self.rows([outcome('^Port', 'x', '')], [service('Port 1')]), [])
        self.assertEqual(self.rows([outcome('^Port', 'x', '{{ LABELS.raw }}')], None), [])

    def test_template_error_is_the_value(self):
        for entries, target in ((None, '^Port'), ([service('Port 1')], 'Port 1')):
            self.assertEqual(
                self.rows([outcome('^Port', 'x', '{{ LABELS.nope.split() }}'),
                           outcome('^Port', '{{ LABELS.nope.split() }}', 'v'),
                           outcome('^Port', 'y', 'fine')], entries),
                [(target, 'x', "'dict object' has no attribute 'nope'"),
                 (target, '', "'dict object' has no attribute 'nope'"),
                 (target, 'y', 'fine')])

    def test_broken_pattern_shows_its_error_as_the_value(self):
        for entries in (None, [service('Port 1')]):
            rows = self.rows([outcome('^(', 'x', '1')], entries)
            self.assertEqual(rows[0][:2], ('^(', 'x'))
            self.assertIn('missing )', rows[0][2])

    def test_object_gets_no_rows(self):
        self.assertEqual(self.sync.debug_host(
            [outcome('^Port', 'x', 'y')], MagicMock(is_object=True),
            {'all': {'HOSTNAME': 'obj01'}}), [])

    def test_no_outcomes_no_rows(self):
        self.assertEqual(self.rows([], [service('Port 1')]), [])

    def test_shows_what_the_export_writes(self):
        outcomes = [outcome('^Port', 'x', '{{ SERVICE }}'), outcome('^Port', 'x', 'late'),
                    outcome('^Port', 'y', '{{ LABELS.raw }}'), outcome('^Port', 'none', '')]
        entries = [service('Port 1', raw='r'), service('Port 2')]
        attributes = host_attributes('srv01', entries)
        self.sync._condition_template = dict
        self.sync.account_id = '7'
        for rule in self.sync.rules_of_host(outcomes, attributes):
            self.assertNotIn('none', ast.literal_eval(rule['value']))
        written = {}
        for entry in entries:
            found = self.sync.labels_of_service(entry, outcomes, attributes)
            written[entry['service']] = {name: value for name, (value, _folder) in found.items()}
        shown = {}
        for name, label, value in self.rows(outcomes, entries):
            shown.setdefault(name, {})[label] = value
        self.assertEqual(shown, written)

    def test_host_folder_is_known_to_the_templates(self):
        with patch.object(self.sync, '_with_host_folder', side_effect=lambda _h, _a, attrs: {
                'all': dict(attrs['all'], HOST_FOLDER='/racks')}):
            self.assertEqual(self.rows([outcome('^Port', 'x', '{{ HOST_FOLDER }}')], None),
                             [('^Port', 'x', '/racks')])


class TestRulesOfHost(RenderedTest):
    """The Checkmk rules of a host"""

    def test_export_takes_hosts_without_objects(self):
        with patch('application.plugins.checkmk.service_labels.Host') as host:
            self.assertIs(self.sync._export_hosts(), host.objects_by_filter.return_value)
        host.objects_by_filter.assert_called_once_with(None)

    def test_filter_of_the_account_decides_when_set(self):
        self.sync.name = 'Checkmk: Export Service Labels'
        self.sync.config = {'settings': {self.sync.name: {'filter': ['shadow_host']}}}
        with patch('application.plugins.checkmk.service_labels.Host') as host:
            self.sync._export_hosts()
        host.objects_by_filter.assert_called_once_with(['shadow_host'])

    def test_exact_service_regex(self):
        regex = exact_service_regex('Port 2.1')
        self.assertEqual(regex, r'Port 2\.1$')
        self.assertTrue(re.match(regex, 'Port 2.1'))
        self.assertFalse(re.match(regex, 'Port 2.10'))
        self.assertFalse(re.match(regex, 'Port 2x1'))

    def test_services_with_same_labels_share_a_rule(self):
        attributes = host_attributes('srv01', [
            service('Port 1', raw='a'), service('Port 2', raw='a'),
            service('Port 3', raw='b'), service('Fan', raw='a')])
        rules = self.sync.rules_of_host(
            [outcome('^Port', 'name', '{{ LABELS.raw }}'),
             outcome('^Port', 'kind', 'port')], attributes)
        self.assertEqual(
            [(r['condition']['service_description']['match_on'],
              ast.literal_eval(r['value'])) for r in rules],
            [([r'Port 1$', r'Port 2$'], {'kind': 'port', 'name': 'a'}),
             ([r'Port 3$'], {'kind': 'port', 'name': 'b'})])
        condition = rules[0]['condition']
        self.assertEqual(condition['host_name'],
                         {'match_on': ['srv01'], 'operator': 'one_of'})
        self.assertEqual(condition['service_description']['operator'], 'one_of')
        self.assertEqual(rules[0]['description'], 'cmdbsyncer_7_service_labels')
        self.assertEqual(rules[0]['folder'], '/')
        self.assertTrue(rules[0]['enforce_value'])

    def test_service_without_the_label_gets_no_rule_and_the_others_do(self):
        attributes = host_attributes('srv01', [
            service('Port 1', raw='e-a'), service('Port 2'), service('Port 3', raw='e-c')])
        rules = self.sync.rules_of_host([outcome('^Port', 'raw', REPAIR)], attributes)
        self.assertEqual(
            [(r['condition']['service_description']['match_on'],
              ast.literal_eval(r['value'])) for r in rules],
            [([r'Port 1$'], {'raw': 'srv01-a'}), ([r'Port 3$'], {'raw': 'srv01-c'})])
        self.sync.log_error.assert_not_called()

    @staticmethod
    def sent(rules):
        return [(r['condition']['service_description']['match_on'],
                 ast.literal_eval(r['value'])) for r in rules]

    def test_no_inventory_writes_the_pattern_with_the_value_of_the_host(self):
        rules = self.sync.rules_of_host(
            [outcome('^Port', 'x', '{{ HOSTNAME }}'), outcome('^Port', 'y', 'z'),
             outcome('^Port', 'x', 'late'),
             outcome('^Fan', 'raw', '{{ LABELS.raw }}'), outcome('^Fan', 'kind', '')],
            {'HOSTNAME': 'srv01'})
        self.assertEqual(self.sent(rules), [(['^Port'], {'x': 'srv01', 'y': 'z'})])
        self.assertEqual(rules[0]['condition']['host_name']['match_on'], ['srv01'])
        self.assertEqual(rules[0]['description'], 'cmdbsyncer_7_service_labels')

    def test_pattern_without_a_known_service_next_to_one_with(self):
        rules = self.sync.rules_of_host(
            [outcome('^Fan', 'x', '1'), outcome('^Port', 'x', '2')],
            host_attributes('srv01', [service('Port 1')]))
        self.assertEqual(self.sent(rules), [(['Port 1$'], {'x': '2'}), (['^Fan'], {'x': '1'})])

    def test_patterns_keep_the_order_of_the_outcomes(self):
        rules = self.sync.rules_of_host(
            [outcome('^Z', 'x', '1'), outcome('^A', 'x', '2'), outcome('^Z', 'y', '3')],
            {'HOSTNAME': 'srv01'})
        self.assertEqual(self.sent(rules), [(['^Z'], {'x': '1', 'y': '3'}), (['^A'], {'x': '2'})])

    def test_patterns_with_the_same_labels_share_a_rule(self):
        rules = self.sync.rules_of_host(
            [outcome('^Z', 'x', '{{ HOSTNAME }}'), outcome('^B', 'room', 'r'),
             outcome('^A', 'x', '{{ HOSTNAME }}')], {'HOSTNAME': 'srv01'})
        self.assertEqual(self.sent(rules), [(['^A', '^Z'], {'x': 'srv01'}),
                                            (['^B'], {'room': 'r'})])

    def test_other_value_in_between_keeps_the_rules_apart(self):
        rules = self.sync.rules_of_host(
            [outcome('^Port 1', 'x', 'a'), outcome('^Port', 'x', 'b'),
             outcome('^Port 2', 'x', 'a')],
            {'HOSTNAME': 'srv01'})
        self.assertEqual(self.sent(rules), [(['^Port 1'], {'x': 'a'}), (['^Port'], {'x': 'b'}),
                                            (['^Port 2'], {'x': 'a'})])

    def test_same_value_in_between_does_not_keep_them_apart(self):
        rules = self.sync.rules_of_host(
            [outcome('^A', 'x', 'a'), outcome('^B', 'x', 'a'), outcome('^B', 'y', 'b'),
             outcome('^C', 'x', 'a')], {'HOSTNAME': 'srv01'})
        self.assertEqual(self.sent(rules), [(['^A', '^C'], {'x': 'a'}),
                                            (['^B'], {'x': 'a', 'y': 'b'})])

    def test_other_folder_is_not_shared_and_not_in_between(self):
        rules = self.sync.rules_of_host(
            [outcome('^A', 'x', 'a', folder='/a'), outcome('^B', 'x', 'b', folder='/b'),
             outcome('^C', 'x', 'a', folder='/a'), outcome('^D', 'x', 'a', folder='/b')],
            {'HOSTNAME': 'srv01'})
        self.assertEqual([(r['folder'], *entry) for r, entry in zip(rules, self.sent(rules))],
                         [('/a', ['^A', '^C'], {'x': 'a'}), ('/b', ['^B'], {'x': 'b'}),
                          ('/b', ['^D'], {'x': 'a'})])

    def test_merging_never_changes_the_winner_on_a_service(self):
        patterns = ['^Port', '^Port 1', '^Port 12', 'Fan', '^Fan 1', '1$']
        names = ['Port 1', 'Port 12', 'Port 2', 'Fan 1', 'My Fan', 'Disk 1', 'Other']
        values = ['a', 'b']
        for pick in itertools.product(values, repeat=len(patterns)):
            outcomes = [outcome(pattern, 'x', value) for pattern, value in zip(patterns, pick)]
            winner = {}
            for name in names:
                found = [value for pattern, value in zip(patterns, pick)
                         if re.search(pattern, name)]
                winner[name] = found[0] if found else None
            result = {}
            for match_on, labels in self.sent(
                    self.sync.rules_of_host(outcomes, {'HOSTNAME': 'srv01'})):
                for name in names:
                    if name not in result and any(re.match(rx, name) for rx in match_on):
                        result[name] = labels['x']
            self.assertEqual({name: result.get(name) for name in names}, winner, pick)

    def test_pattern_means_the_same_in_checkmk(self):
        for pattern, name, hits in (('^Port', 'Port 1', True), ('^Port', 'My Port', False),
                                    ('Port', 'My Port', True), ('Port|Fan', 'My Fan', True),
                                    ('Port|Fan', 'Disk', False)):
            regex = checkmk_service_regex(pattern)
            self.assertEqual(bool(re.search(pattern, name)), hits)
            self.assertEqual(bool(re.match(regex, name)), hits, regex)

    def test_broken_pattern_is_not_sent(self):
        rules = self.sync.rules_of_host(
            [outcome('^(', 'x', '1'), outcome('^Port', 'x', '2')], {'HOSTNAME': 'srv01'})
        self.assertEqual(self.sent(rules), [(['^Port'], {'x': '2'})])
        self.sync.log_error.assert_called_once()

    def test_pattern_folder_and_scope_apply(self):
        outcomes = [outcome('^Port', 'x', '1', folder='/a//b/'),
                    outcome('^Port', 'y', '2', folder='/other')]
        self.sync.config = {'limit_by_folders': '/a', 'settings': {}}
        rules = self.sync.rules_of_host(outcomes, {'HOSTNAME': 'srv01'})
        self.assertEqual([r['folder'] for r in rules], ['/a/b'])

    def test_debug_lists_what_the_export_writes_without_inventory(self):
        outcomes = [outcome('^Port', 'x', '{{ HOSTNAME }}'), outcome('^Port', 'y', 'z'),
                    outcome('^Fan', 'raw', '{{ LABELS.raw }}')]
        attributes = {'HOSTNAME': 'srv01'}
        shown = {}
        for row in self.sync.debug_host(outcomes, MagicMock(is_object=False),
                                        {'all': attributes}):
            shown.setdefault(row['service'], {})[row['name']] = row['value']
        written = {match_on[0]: labels for match_on, labels
                   in self.sent(self.sync.rules_of_host(outcomes, attributes))}
        self.assertEqual(written, {'^Port': {'x': 'srv01', 'y': 'z'}})
        self.assertEqual(shown, written)

    def test_folders_split_rules_and_scope_applies(self):
        attributes = host_attributes('srv01', [service('Port 1')])
        outcomes = [outcome('^Port', 'x', '1', folder='/a//b/'),
                    outcome('^Port', 'y', '2', folder='/other')]
        rules = self.sync.rules_of_host(outcomes, attributes)
        self.assertEqual([r['folder'] for r in rules], ['/a/b', '/other'])
        self.sync.config = {'limit_by_folders': '/a', 'settings': {}}
        rules = self.sync.rules_of_host(outcomes, attributes)
        self.assertEqual([r['folder'] for r in rules], ['/a/b'])

    def test_hosts_with_same_rule_are_merged(self):
        for name in ('srv01', 'srv02'):
            for rule in self.sync.rules_of_host(
                    [outcome('^Port', 'x', 'same')],
                    host_attributes(name, [service('Port 1')])):
                self.sync._collect_rule(SERVICE_LABEL_RULESET, rule)
        self.sync.optimize_rules()
        rules = self.sync.rulsets_by_type[SERVICE_LABEL_RULESET]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['condition']['host_name']['match_on'],
                         ['srv01', 'srv02'])


class TestStackedDevices(RenderedTest):
    """One host with several stacked devices, each with its own name on its services"""

    SERVICES = [service('Port 1.1', raw='e-unit1'), service('Port 1.1 Fuse', raw='e-unit1'),
                service('Port 2.1', raw='e-unit2'), service('Port 3.1', raw='e-unit3'),
                service('Port 3.2', raw='e-input2')]
    FROM_LABEL = outcome('^Port', 'name',
                         "{% set l = LABELS.raw|default('') %}"
                         "{% if l %}rack-{{ l[2:] }}{% endif %}")

    def test_every_service_gets_the_name_of_its_own_device_and_input(self):
        rules = self.sync.rules_of_host([self.FROM_LABEL], host_attributes('srv01', self.SERVICES))
        self.assertEqual(
            [(r['condition']['service_description']['match_on'],
              ast.literal_eval(r['value'])) for r in rules],
            [(['Port 3\\.2$'], {'name': 'rack-input2'}),
             (['Port 1\\.1 Fuse$', 'Port 1\\.1$'], {'name': 'rack-unit1'}),
             (['Port 2\\.1$'], {'name': 'rack-unit2'}),
             (['Port 3\\.1$'], {'name': 'rack-unit3'})])

    def test_a_label_shared_by_the_devices_does_not_merge_their_names(self):
        rules = self.sync.rules_of_host([self.FROM_LABEL, outcome('^Port', 'room', 'r1')],
                                        host_attributes('srv01', self.SERVICES))
        self.assertEqual(len(rules), 4)
        for rule in rules:
            self.assertEqual(ast.literal_eval(rule['value'])['room'], 'r1')

    def test_without_service_data_no_name_is_sent_only_what_the_host_knows(self):
        rules = self.sync.rules_of_host([self.FROM_LABEL, outcome('^Port', 'room', 'r1')],
                                        {'HOSTNAME': 'srv01'})
        self.assertEqual([ast.literal_eval(r['value']) for r in rules], [{'room': 'r1'}])

    def test_card_shows_the_same_names(self):
        rows = self.sync.debug_host([self.FROM_LABEL], MagicMock(is_object=False),
                                    {'all': host_attributes('srv01', self.SERVICES)})
        self.assertEqual({row['service']: row['value'] for row in rows}, {
            'Port 1.1': 'rack-unit1', 'Port 1.1 Fuse': 'rack-unit1', 'Port 2.1': 'rack-unit2',
            'Port 3.1': 'rack-unit3', 'Port 3.2': 'rack-input2'})

    def test_setup_rules_still_take_the_objects(self):
        sync = make_sync(CheckmkRuleSync)
        with patch('application.plugins.checkmk.cmk_rules.Host') as host:
            self.assertIs(sync._export_hosts(), host.active_non_template.return_value)


class TestHostCondition(unittest.TestCase):
    """Hosts with a label are selected by a standard condition of the rule"""

    @staticmethod
    def condition(value_match='in', value='raw', negate=False):
        return {'match_type': 'tag',
                'tag': PER_SERVICE_LABELS_ATTRIBUTE, 'tag_match': 'equal',
                'tag_match_negate': False,
                'value': value, 'value_match': value_match,
                'value_match_negate': negate}

    def matches(self, attributes, **condition):
        engine = ServiceLabelRule()
        engine.attributes = attributes
        return engine.handle_match(self.condition(**condition), attributes['HOSTNAME'])

    def test_host_with_the_label_on_a_service(self):
        attributes = host_attributes('srv01', [service('Fan'), service('Port 1', raw='r')])
        self.assertTrue(self.matches(attributes))

    def test_host_without_the_label(self):
        attributes = host_attributes('srv01', [service('Fan'), service('Port 1', other='r')])
        self.assertFalse(self.matches(attributes))
        self.assertTrue(self.matches(attributes, negate=True))

    def test_host_without_the_attribute(self):
        self.assertFalse(self.matches({'HOSTNAME': 'srv01'}))


def cmk_rule(rule_id, description, value="{'x': 'y'}", service_regex=r'Port 1$'):
    return {
        'id': rule_id,
        'extensions': {
            'folder': '/',
            'value_raw': value,
            'properties': {'description': description, 'comment': ''},
            'conditions': {
                'host_tags': [], 'service_label_groups': [], 'host_label_groups': [],
                'host_name': {'match_on': ['srv01'], 'operator': 'one_of'},
                'service_description': {'match_on': [service_regex], 'operator': 'one_of'},
            },
        },
    }


class TestOwnership(RenderedTest):
    """The export and foreign rules"""

    def setUp(self):
        super().setUp()
        patcher = patch('application.plugins.checkmk.cmk_rules.make_progress')
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_clean(self, cmk_rules, wanted=None):
        self.sync.rulsets_by_type = {SERVICE_LABEL_RULESET: wanted or []}
        calls = []

        def request(url, method='GET', **_kwargs):
            calls.append((method, url))
            return {'value': cmk_rules}, {}

        with patch.object(self.sync, 'request', side_effect=request), patch('builtins.print'):
            self.sync.clean_rules()
        return [url for method, url in calls if method == 'DELETE']

    def test_marker_does_not_overlap_the_setup_rules(self):
        setup_rules = make_sync(CheckmkRuleSync)
        ours = cmk_rule('a', 'cmdbsyncer_7_service_labels')
        theirs = cmk_rule('b', 'cmdbsyncer_7')
        named = cmk_rule('c', 'cmdbsyncer_7 - A setup rule')
        self.assertTrue(self.sync._owns_rule(ours))
        self.assertFalse(self.sync._owns_rule(theirs))
        self.assertFalse(self.sync._owns_rule(named))
        self.assertFalse(setup_rules._owns_rule(ours))
        self.assertTrue(setup_rules._owns_rule(theirs))

    def test_removes_only_its_own_rules(self):
        deleted = self.run_clean([
            cmk_rule('stale', 'cmdbsyncer_7_service_labels'),
            cmk_rule('setup', 'cmdbsyncer_7'),
            cmk_rule('other_account', 'cmdbsyncer_8_service_labels'),
            cmk_rule('hand_made', 'written by hand'),
            cmk_rule('hash', 'a' * 128),
        ])
        self.assertEqual(len(deleted), 1)
        self.assertIn('stale', deleted[0])

    def test_unchanged_rule_is_left_alone(self):
        wanted = self.sync.rules_of_host(
            [outcome('^Port 1', 'x', 'y')],
            host_attributes('srv01', [service('Port 1')]))
        self.assertEqual(self.run_clean(
            [cmk_rule('same', 'cmdbsyncer_7_service_labels')], wanted), [])
        self.assertTrue(wanted[0]['_skip_create'])

    def test_no_rule_wanted_any_more_still_cleans_up(self):
        hosts = MagicMock()
        hosts.count.return_value = 0
        hosts.__iter__.return_value = iter([])
        self.sync.actions = MagicMock(rules=[])
        with patch.object(self.sync, '_export_hosts', return_value=hosts), \
             patch.object(self.sync, 'request', return_value=({'value': []}, {})), \
             patch('builtins.print'):
            self.sync.calculate_rules()
        self.assertEqual(self.sync.rulsets_by_type, {SERVICE_LABEL_RULESET: []})

    def test_dry_run_sends_nothing(self):
        self.sync.dry_run = True
        self.sync.rulsets_by_type = {SERVICE_LABEL_RULESET: self.sync.rules_of_host(
            [outcome('^Port', 'x', 'y')],
            host_attributes('srv01', [service('Port 1')]))}
        calls = []

        def request(_url, method='GET', **_kwargs):
            calls.append(method)
            stale = cmk_rule('stale', 'cmdbsyncer_7_service_labels', service_regex='Port 9$')
            return {'value': [stale]}, {}

        with patch.object(self.sync, 'request', side_effect=request), patch('builtins.print'):
            self.sync.clean_rules()
            self.sync.create_rules()
        self.assertEqual(set(calls), {'GET'})
        self.assertIn('CREATE', [entry[0] for entry in self.sync.dry_run_plan])


# The condition as it is entered in the GUI: a service with only one of them.
ONLY_RAW = r".*\{(?![^}]*friendly)[^}]*raw"
ONLY_FRIENDLY = r".*\{(?![^}]*raw)[^}]*friendly"
REPAIR_RAW = ("{% set l = LABELS.raw|default(LABELS.friendly|default('')) %}"
              "{% if l.startswith('e-') %}{{ HOSTNAME }}-{{ l[2:] }}{% else %}{{ l }}{% endif %}")
OUR_MARK = 'cmdbsyncer_7_service_labels'


class TestKeptRules(RenderedTest):
    """A host no longer matching because of its own rule keeps that rule"""

    def setUp(self):
        super().setUp()
        patcher = patch('application.plugins.checkmk.cmk_rules.make_progress')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sync.actions = MagicMock(rules=[self.rule(REPAIR_RAW)])

    @staticmethod
    def rule(value):
        rule = MagicMock()
        rule.to_mongo.return_value = {'outcomes': [
            outcome('^Port', 'friendly', value, folder='/')]}
        return rule

    @staticmethod
    def fires(attributes):
        text = str(attributes.get(PER_SERVICE_LABELS_ATTRIBUTE, []))
        return bool(re.match(ONLY_RAW, text) or re.match(ONLY_FRIENDLY, text))

    def export(self, hosts, in_checkmk):
        """
        One export as the real one goes: hosts as ``{name: services}``, and
        what it sends to Checkmk
        """
        self.sync.rulsets_by_type = {}
        self.sync._rule_signatures = {}
        self.sync._cmk_order_by_ruleset = {}
        calls = []

        def request(url, method='GET', **_kwargs):
            if method == 'GET':
                return {'value': in_checkmk}, {}
            calls.append((method, url))
            return {}, {'ETag': 'x'}

        db_hosts = MagicMock()
        db_hosts.count.return_value = len(hosts)
        db_hosts.__iter__.return_value = iter(
            MagicMock(hostname=name) for name in hosts)

        def attributes_of(db_host, *_args, **_kwargs):
            return {'all': host_attributes(db_host.hostname, hosts[db_host.hostname])}

        def outcomes_of(db_host, *_args, **_kwargs):
            attributes = host_attributes(db_host.hostname, hosts[db_host.hostname])
            if not self.fires(attributes):
                return {}
            return {'default': self.sync.every_outcome}

        self.sync.actions.get_outcomes = outcomes_of
        with patch.object(self.sync, 'request', side_effect=request), \
             patch.object(self.sync, '_export_hosts', return_value=db_hosts), \
             patch.object(self.sync, 'get_attributes', side_effect=attributes_of), \
             patch.object(self.sync, 'flush_host_cache'), \
             patch.object(self.sync, '_calculate_template_rules'), \
             patch('builtins.print'):
            self.sync.calculate_rules()
            self.sync.optimize_rules()
            self.sync.clean_rules()
            self.sync.create_rules()
        return calls

    def stored(self, rule_id, value, services, hosts=('srv01',)):
        rule = cmk_rule(rule_id, OUR_MARK, value=repr(value))
        conditions = rule['extensions']['conditions']
        conditions['service_description']['match_on'] = \
            sorted(exact_service_regex(name) for name in services)
        conditions['host_name']['match_on'] = list(hosts)
        return rule

    def test_the_regexes_fire_on_one_label_only(self):
        self.assertTrue(self.fires(host_attributes('h', [service('Port 1', raw='e-a')])))
        self.assertTrue(self.fires(host_attributes('h', [service('Port 1', friendly='e-a')])))
        self.assertTrue(self.fires(host_attributes('h', [
            service('Port 1', friendly='h-a', raw='e-a'),
            service('Port 2', other='x', raw='e-b')])))
        self.assertFalse(self.fires(host_attributes('h', [
            service('Port 1', friendly='h-a', other='x', raw='e-a')])))
        self.assertFalse(self.fires(host_attributes('h', [service('Port 1')])))

    def test_only_raw_writes_the_rule(self):
        calls = self.export({'srv01': [service('Port 1', raw='e-a')]}, [])
        self.assertEqual([method for method, _url in calls if method == 'DELETE'], [])
        self.assertEqual(self.sync.rulsets_by_type[SERVICE_LABEL_RULESET][0]['value'],
                         "{'friendly': 'srv01-a'}")

    def test_both_labels_nothing_is_sent(self):
        stored = self.stored('r1', {'friendly': 'srv01-a'}, ['Port 1'])
        hosts = {'srv01': [service('Port 1', friendly='srv01-a', raw='e-a')]}
        for _run in range(3):
            self.assertEqual(self.export(hosts, [stored]), [])

    def test_both_labels_without_a_rule_of_ours_nothing_is_written(self):
        hosts = {'srv01': [service('Port 1', friendly='by-hand', raw='e-a')]}
        self.assertEqual(self.export(hosts, []), [])

    def test_merged_rule_keeps_the_host_not_matching(self):
        stored = self.stored('r1', {'friendly': 'a'}, ['Port 1'], ('srv01', 'srv02'))
        self.sync.actions = MagicMock(rules=[self.rule('a')])
        hosts = {'srv01': [service('Port 1', raw='a')],
                 'srv02': [service('Port 1', friendly='a', raw='a')]}
        self.assertEqual(self.export(hosts, [stored]), [])

    def test_new_service_on_a_kept_host(self):
        stored = self.stored('r1', {'friendly': 'srv01-a'}, ['Port 1'])
        hosts = {'srv01': [service('Port 1', friendly='srv01-a', raw='e-a'),
                           service('Port 2', raw='e-b')]}
        calls = self.export(hosts, [stored])
        self.assertEqual([method for method, _url in calls if method == 'DELETE'], [])
        values = [rule['value'] for rule in self.sync.rulsets_by_type[SERVICE_LABEL_RULESET]]
        self.assertEqual(sorted(values), ["{'friendly': 'srv01-a'}", "{'friendly': 'srv01-b'}"])

    def test_host_not_matching_still_knows_its_folder(self):
        rule = self.rule(REPAIR_RAW)
        rule.to_mongo.return_value['outcomes'][0]['folder'] = '{{ HOST_FOLDER }}'
        self.sync.actions = MagicMock(rules=[rule])
        hosts = {'srv01': [service('Port 1', friendly='srv01-a', raw='e-a')]}
        stored = self.stored('r1', {'friendly': 'srv01-a'}, ['Port 1'])
        stored['extensions']['folder'] = '/racks'

        def with_folder(_db_host, _actions, attributes):
            return {'all': dict(attributes['all'], HOST_FOLDER='/racks')}

        with patch.object(self.sync, '_with_host_folder', side_effect=with_folder):
            self.assertEqual(self.export(hosts, [stored]), [])

    def assert_removed(self, hosts, stored):
        calls = self.export(hosts, [stored])
        self.assertEqual(calls, [('DELETE', '/objects/rule/r1')])

    def test_host_gone_removes_the_rule(self):
        self.assert_removed({}, self.stored('r1', {'friendly': 'srv01-a'}, ['Port 1']))

    def test_rule_gone_in_the_syncer_removes_the_rule(self):
        self.sync.actions = MagicMock(rules=[])
        self.assert_removed({'srv01': [service('Port 1', friendly='srv01-a', raw='e-a')]},
                            self.stored('r1', {'friendly': 'srv01-a'}, ['Port 1']))

    def test_changed_raw_name_removes_the_rule_then_it_fires(self):
        stored = self.stored('r1', {'friendly': 'srv01-a'}, ['Port 1'])
        self.assert_removed({'srv01': [service('Port 1', friendly='srv01-a', raw='e-new')]},
                            stored)
        self.export({'srv01': [service('Port 1', raw='e-new')]}, [])
        self.assertEqual(self.sync.rulsets_by_type[SERVICE_LABEL_RULESET][0]['value'],
                         "{'friendly': 'srv01-new'}")

    def test_foreign_rule_is_not_read_as_ours(self):
        foreign = self.stored('r9', {'friendly': 'srv01-a'}, ['Port 1'])
        foreign['extensions']['properties']['description'] = 'written by hand'
        hosts = {'srv01': [service('Port 1', friendly='srv01-a', raw='e-a')]}
        self.assertEqual(self.export(hosts, [foreign]), [])
        self.assertEqual(self.sync.rulsets_by_type[SERVICE_LABEL_RULESET], [])

    def test_failed_read_sends_nothing(self):
        with patch.object(self.sync, 'request', side_effect=ConnectionError('down')), \
             patch('builtins.print'):
            with self.assertRaises(ConnectionError):
                self.sync.calculate_rules()


# A label repair script as it is found in the field: the labels of a device
# plugin are read from the monitoring, rewritten per service and written back
# as rules. Below it is ported as it is, odd cases included, so the rules can be
# held against it. Names are neutral: racks with their sensors, and small
# devices with one inlet.
ROOMS = {letter: 'room-1' for letter in 'abcdefgh'}
ROOMS.update({letter: 'room-2' for letter in 'jklm'})
ROOMS.update({letter: 'room-3' for letter in 'nopqrst'})
ROOMS.update({letter: 'room-4' for letter in 'wx'})
ROOMS.update({letter: 'room-5' for letter in 'yz'})
ROOMS.update({letter: 'N/A' for letter in 'iuv'})
NAME = 'display_name'


def script_room(site, slot):
    if site == 'dc2' and slot[:1] == 'r' and 1 <= int(slot[1:]) <= 16:
        return 'room-6'
    if site == 'dc1' and slot == 'core':
        return 'room-7'
    if site == 'dc1' and slot == 'tst':
        return 'room-8'
    return ROOMS[slot[:1]]


def script_group(service_name):
    """The script reads one group of services and treats them as one key"""
    if service_name == 'Inlet C':
        return 'Inlet C'
    if service_name.startswith('Outlet') or service_name == 'Inlet 1.1':
        return 'Outlet|Inlet 1.1'
    if 'Sensor Master' in service_name:
        return 'Humidity Sensor Master|Temperature Sensor Master'
    if hit := re.match(r'(Humidity|Temperature) Sensor Rack (\d+)$', service_name):
        return f'Humidity Sensor Rack {hit.group(2)}|Temperature Sensor Rack {hit.group(2)}'
    return service_name


def script_rewrite(host, group, labels):  # pylint: disable=too-many-branches
    """The rewrite of the script for one group of services"""
    labels = dict(labels)
    host_parts = host.split('-')
    building = '-'.join(host_parts[:3])
    parts = labels[NAME].split('-')
    labels['room'] = script_room(host_parts[2], host_parts[3])
    if host_parts[3] == 'tst':
        labels['test_device'] = host_parts[0]
    res = re.match(r'Humidity Sensor Master|Humidity Sensor Rack (\d+)', group)
    if res:
        labels['enclosure'] = 'cold_aisle'
        if parts[1] == 'test' and 'slave' in parts[2]:
            labels[NAME] = f'{building}-tst-a{int(res.group(1)) + 1}'
        elif len(parts) > 3 and parts[3] == 'tst':
            pass
        else:
            labels[NAME] = host
    if re.match('Inlet C', group) or re.match('Outlet', group):
        labels[NAME] = host
    res = re.match(r'Inlet (\d+).1', group)
    if res:
        if parts[0] == 'rack' and len(parts) == 5:
            if parts[4] in ('aa', 'ab', 'ba', 'bb'):
                labels[NAME] = f'{building}-{parts[3]}{parts[4][0]}-{parts[4][1]}'
            elif parts[3] == 'tes':
                labels[NAME] = f'{building}-tst-a{res.group(1)}'
        elif len(parts) == 4:
            if parts[3].startswith(('old', 'alt')):
                labels[NAME] = f'{building}-{parts[3][3:6]}-{parts[3][6:]}'
            elif parts[1] == 'test' and parts[2] == 'master':
                labels[NAME] = host
            elif parts[1] == 'test' and 'slave' in parts[2]:
                labels[NAME] = f'{building}-tst-a{res.group(1)}'
        else:
            labels[NAME] = f"{building}-{'-'.join(parts[1:])}"
    return labels


# The same as rules, entered in the GUI as they stand here.
SET_NAME = ("{% set b = HOSTNAME.split('-')[:3]|join('-') %}"
            f"{{% set l = LABELS.{NAME}|default('') %}}{{% set p = l.split('-') %}}")
INLET_NAME = SET_NAME + (
    "{% if l %}"
    "{% if p[0] == 'rack' and p|length == 5 %}"
    "{% if p[4] in ['aa', 'ab', 'ba', 'bb'] %}{{ b }}-{{ p[3] }}{{ p[4][0] }}-{{ p[4][1] }}"
    "{% elif p[3] == 'tes' %}{{ b }}-tst-a{{ MATCH[1] }}"
    "{% else %}{{ l }}{% endif %}"
    "{% elif p|length == 4 %}"
    "{% if p[3][:3] in ['old', 'alt'] %}{{ b }}-{{ p[3][3:6] }}-{{ p[3][6:] }}"
    "{% elif p[1] == 'test' and p[2] == 'master' %}{{ HOSTNAME }}"
    "{% elif p[1] == 'test' and 'slave' in p[2] %}{{ b }}-tst-a{{ MATCH[1] }}"
    "{% else %}{{ l }}{% endif %}"
    "{% elif l.startswith(b ~ '-') %}{{ l }}"
    "{% else %}{{ b }}-{{ p[1:]|join('-') }}{% endif %}"
    "{% endif %}")
SENSOR_NAME = SET_NAME + (
    "{% if p[1] == 'test' and 'slave' in p[2] %}{{ b }}-tst-a{{ MATCH[1]|int + 1 }}"
    "{% elif p|length > 3 and p[3] == 'tst' %}{{ l }}"
    "{% else %}{{ HOSTNAME }}{% endif %}")
MASTER_SENSOR_NAME = SET_NAME + (
    "{% if p|length > 3 and p[3] == 'tst' %}{{ l }}{% else %}{{ HOSTNAME }}{% endif %}")
ROOM = ("{% set p = HOSTNAME.split('-') %}{% set s = p[3] %}"
        f"{{% set rooms = {ROOMS!r} %}}"
        "{% if p[2] == 'dc2' and s[:1] == 'r' and s[1:]|int >= 1 and s[1:]|int <= 16 %}room-6"
        "{% elif p[2] == 'dc1' and s == 'core' %}room-7"
        "{% elif p[2] == 'dc1' and s == 'tst' %}room-8"
        "{% else %}{{ rooms[s[:1]] }}{% endif %}")
TEST_DEVICE = "{% set p = HOSTNAME.split('-') %}{% if p[3] == 'tst' %}{{ p[0] }}{% endif %}"

NUMBER = r'([2-9]|[12]\d|30)'
MASTER_SERVICES = r'^(Outlet|Inlet 1\.1$)'
MASTER_SENSORS = r'^(Humidity|Temperature) Sensor Master'
RACK_SENSORS = rf'^(?:Humidity|Temperature) Sensor Rack {NUMBER}$'
INLETS = rf'^Inlet {NUMBER}\.1$'
ALL_RACK = f'{MASTER_SERVICES}|{MASTER_SENSORS}|{RACK_SENSORS}|{INLETS}'

RACK_OUTCOMES = [
    outcome(MASTER_SERVICES, NAME, '{{ HOSTNAME }}'),
    outcome(MASTER_SENSORS, NAME, MASTER_SENSOR_NAME),
    outcome(RACK_SENSORS, NAME, SENSOR_NAME),
    outcome(INLETS, NAME, INLET_NAME),
    outcome(f'{MASTER_SENSORS}|{RACK_SENSORS}', 'enclosure', 'cold_aisle'),
    outcome(ALL_RACK, 'room', ROOM),
    outcome(ALL_RACK, 'test_device', TEST_DEVICE),
]
SMALL_DEVICE_OUTCOMES = [
    outcome('^Inlet C', NAME, '{{ HOSTNAME }}'),
    outcome('^Inlet C', 'room', ROOM),
    outcome('^Inlet C', 'test_device', TEST_DEVICE),
]


def rack_services(raw_of_host):
    """A rack with the raw names its device plugin reports"""
    master, slaves = raw_of_host
    services = [service('Outlet 1', **{NAME: master}), service('Inlet 1.1', **{NAME: master}),
                service('Humidity Sensor Master', **{NAME: master}),
                service('Temperature Sensor Master', **{NAME: master})]
    for number, raw in slaves.items():
        services += [service(f'Inlet {number}.1', **{NAME: raw}),
                     service(f'Humidity Sensor Rack {number}', **{NAME: raw}),
                     service(f'Temperature Sensor Rack {number}', **{NAME: raw})]
    return services


RACKS = {
    'rack-x-dc1-s04-b': ('e-s04-b', {2: 'e-s05-a', 3: 'e-s05-b', 10: 'e-s08-b'}),
    'rack-x-dc1-a04-a': ('e-a04-a', {2: 'e-a03-b'}),
    'rack-x-dc1-core-a': ('e-core-a', {2: 'e-core-b'}),
    'rack-x-dc2-r07-a': ('e-r07-a', {2: 'e-r08-a'}),
    'rack-x-dc2-z01-a': ('e-z01-a', {}),
    'rack-x-dc1-i01-a': ('e-i01-a', {}),
    # Old formats of names, each one with its own treatment
    'rack-x-dc1-b02-a': ('e-b02-a', {2: 'rack-x-dc1-b03-aa', 3: 'rack-x-dc1-b03-bb',
                                     4: 'e-b-c-oldb02x', 5: 'e-b-c-altb02y',
                                     6: 'e-b-c-other'}),
    # The test rack
    'rack-x-dc1-tst-a1': ('e-test-master-rack', {2: 'e-test-slave1', 3: 'e-test-slave2',
                                                 4: 'rack-x-dc1-tes-q'}),
}
SMALL_DEVICES = {
    'ups-x-dc1-c01': 'e-c01',
    'ups-x-dc2-r02': 'e-r02',
    'ups-x-dc1-tst': 'e-test-ups',
}


class TestAgainstTheScript(RenderedTest):
    """The rules give what the script gives, on the first and on the next run"""

    def compare(self, host, entries, outcomes):
        """Holds rules and script against each other. Returns the next read."""
        compared = 0
        next_read = []
        for entry in entries:
            expected = script_rewrite(host, script_group(entry['service']), entry['labels'])
            found = self.sync.labels_of_service(
                entry, outcomes, host_attributes(host, entries))
            got = {name: value for name, (value, _folder) in found.items()}
            self.assertEqual(got.get(NAME, entry['labels'][NAME]), expected[NAME],
                             f"{host} {entry['service']}")
            self.assertEqual({k: v for k, v in got.items() if k != NAME},
                             {k: v for k, v in expected.items() if k != NAME},
                             f"{host} {entry['service']}")
            compared += 1
            next_read.append({'service': entry['service'],
                              'labels': {**entry['labels'], **got}})
        return next_read, compared

    def check(self, host, entries, outcomes):
        first, compared = self.compare(host, entries, outcomes)
        # With the rules active Checkmk reports their value, not the raw one.
        second, _ = self.compare(host, first, outcomes)
        self.assertEqual(first, second, f"{host}: the repair is not stable")
        third, _ = self.compare(host, second, outcomes)
        self.assertEqual(second, third, f"{host}: the repair is not stable")
        return compared

    def test_racks(self):
        compared = sum(self.check(host, rack_services(raw), RACK_OUTCOMES)
                       for host, raw in RACKS.items())
        self.assertGreater(compared, 50)

    def test_small_devices(self):
        for host, raw in SMALL_DEVICES.items():
            self.check(host, [service('Inlet C', **{NAME: raw})], SMALL_DEVICE_OUTCOMES)

    def test_inlet_without_the_label_is_left_out_and_the_run_goes_on(self):
        host = 'rack-x-dc1-s04-b'
        entries = rack_services(RACKS[host])
        for entry in entries:
            if entry['service'] == 'Inlet 2.1':
                entry['labels'] = {}
        by_service = {}
        for rule in self.sync.rules_of_host(RACK_OUTCOMES, host_attributes(host, entries)):
            for regex in rule['condition']['service_description']['match_on']:
                by_service[regex] = ast.literal_eval(rule['value'])
        # What comes from the host name stays, only the rebuilt name is missing.
        self.assertNotIn(NAME, by_service[r'Inlet 2\.1$'])
        self.assertEqual(by_service[r'Inlet 2\.1$']['room'], 'room-3')
        self.assertEqual(by_service[r'Inlet 3\.1$'][NAME], 'rack-x-dc1-s05-b')
        self.sync.log_error.assert_not_called()

    def test_slave_name_per_service(self):
        host = 'rack-x-dc1-s04-b'
        entries = rack_services(RACKS[host])
        rules = self.sync.rules_of_host(RACK_OUTCOMES, host_attributes(host, entries))
        by_service = {}
        for rule in rules:
            for regex in rule['condition']['service_description']['match_on']:
                by_service[regex] = ast.literal_eval(rule['value'])
        self.assertEqual(by_service[r'Inlet 2\.1$'][NAME], 'rack-x-dc1-s05-a')
        self.assertEqual(by_service[r'Inlet 10\.1$'][NAME], 'rack-x-dc1-s08-b')
        self.assertEqual(by_service[r'Humidity Sensor Rack 2$'][NAME], host)
        self.assertEqual(by_service[r'Humidity Sensor Rack 2$']['enclosure'], 'cold_aisle')
        self.assertEqual(by_service[r'Outlet 1$'][NAME], host)
        self.assertNotIn('enclosure', by_service[r'Outlet 1$'])
        self.assertNotIn('test_device', by_service[r'Outlet 1$'])
        # One rule for all services ending up with the same labels.
        self.assertLess(len(rules), len(entries))

    def test_name_of_many_parts_stays_stable_where_the_script_grows(self):
        host = 'rack-x-dc1-s04-b'
        raw = {NAME: 'e-s05-a-b-c'}
        first = script_rewrite(host, 'Inlet 2.1', raw)
        self.assertNotEqual(script_rewrite(host, 'Inlet 2.1', first)[NAME], first[NAME])

        inlet = RACK_OUTCOMES[3]
        entry = service('Inlet 2.1', **raw)
        name = self.sync.labels_of_service(
            entry, [inlet], host_attributes(host, [entry]))[NAME][0]
        self.assertEqual(name, first[NAME])
        again = service('Inlet 2.1', **{NAME: name})
        self.assertEqual(self.sync.labels_of_service(
            again, [inlet], host_attributes(host, [again]))[NAME][0], name)

    def test_repair_of_an_already_rebuilt_name_is_stable(self):
        entry = service('Inlet 2.1', **{NAME: 'rack-x-dc1-s05-a'})
        found = self.sync.labels_of_service(
            entry, [RACK_OUTCOMES[3]], host_attributes('rack-x-dc1-s04-b', [entry]))
        self.assertEqual(found[NAME][0], 'rack-x-dc1-s05-a')


if __name__ == '__main__':
    unittest.main()
