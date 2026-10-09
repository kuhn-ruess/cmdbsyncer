"""
Tests for the List Source of Checkmk Setup Rules: the parser, the merge of
service conditions, the per-row rendering and the export (dry run) path.
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from application.plugins.checkmk.list_source import (
    check_list_rule,
    column_name,
    detect_delimiter,
    merge_service_conditions,
    outcome_templates,
    parse_list_source,
    row_context,
    rule_uses_list,
    template_variables,
    MAX_ROWS,
)
from tests import make_checkmk_rule_sync, real_get_list, real_render_jinja


class TestColumnName(unittest.TestCase):
    """Header cells become Jinja variable names"""

    def test_spaces_and_case(self):
        self.assertEqual(column_name(' Service Level '), 'service_level')

    def test_special_characters_collapse(self):
        self.assertEqual(column_name('Hard-State (min)'), 'hard_state_min')

    def test_leading_digit(self):
        self.assertEqual(column_name('2nd Team'), '_2nd_team')

    def test_nothing_usable(self):
        self.assertEqual(column_name(' -- '), '')

    def test_already_a_variable(self):
        self.assertEqual(column_name('max_attempts'), 'max_attempts')

    def test_upper_case_and_dots(self):
        self.assertEqual(column_name('Check.Interval'), 'check_interval')

    def test_non_ascii_letters_become_underscores(self):
        # Only ASCII letters are valid in a plain Jinja variable name.
        self.assertEqual(column_name('Größe'), 'gr_e')

    def test_parser_reports_the_normalised_names(self):
        parsed = parse_list_source("Service Name;Max. Attempts\na;1\n")
        self.assertEqual(parsed.columns, ['service_name', 'max_attempts'])


class TestRuleUsesList(unittest.TestCase):
    """The rule source switch decides; only rules without one guess"""

    def test_list_mode(self):
        self.assertTrue(rule_uses_list('list', 'service\nDisk C:'))

    def test_list_mode_without_list(self):
        # Still a list rule: the save check refuses the empty list.
        self.assertTrue(rule_uses_list('list', ''))

    def test_host_mode_ignores_a_left_over_list(self):
        self.assertFalse(rule_uses_list('hosts', 'service\nDisk C:'))

    def test_rule_without_mode_follows_the_list(self):
        self.assertTrue(rule_uses_list(None, 'service\nDisk C:'))
        self.assertFalse(rule_uses_list(None, '  '))
        self.assertFalse(rule_uses_list('', None))


class TestCheckListRule(unittest.TestCase):
    """What the form reports when a rule is saved"""

    def test_host_rule_is_not_checked(self):
        _parsed, errors, warnings = check_list_rule(
            'hosts', 'a;b\n1;2;3', [('Outcome 1, Value', '{{ x }}')])
        self.assertEqual((errors, warnings), ([], []))

    def test_empty_list_in_list_mode(self):
        _parsed, errors, _warnings = check_list_rule('list', ' ', [])
        self.assertIn("the list is empty", errors[0])

    def test_parser_error_names_line_cell_and_columns(self):
        _parsed, errors, _warnings = check_list_rule(
            'list', 'service;level\nDisk C:;gold\nMemory;silver;extra\n', [])
        self.assertEqual(errors, [
            "List: Line 3: cell 3 ('extra') has no column, the first line "
            "names only 2 columns (service, level). Check the separator or "
            "quote the cell"])

    def test_unknown_variable_warns_with_the_columns(self):
        _parsed, errors, warnings = check_list_rule(
            'list', 'Service;Level\nDisk C:;gold\n',
            [('Outcome 1, Value', '{{ levl }}'),
             ('Outcome 1, Condition Service name', '{{ service }}$')])
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [
            "Outcome 1, Value: '{{ levl }}' is not a column of the list, it "
            "renders empty and such rows create no rule. Columns: "
            "{{ service }}, {{ level }}"])

    def test_row_names_and_globals_are_known(self):
        _parsed, _errors, warnings = check_list_rule(
            'list', 'service\nDisk C:\n',
            [('Outcome 1, Value',
              "{{ row.service }} {{ row_idx }} {{ loop }} {{ get_list(service) }}")],
            known_names={'get_list'})
        self.assertEqual(warnings, [])


class TestTemplateVariables(unittest.TestCase):
    """Variables read by a template"""

    def test_variables(self):
        self.assertEqual(template_variables("{{ a }} {% if b %}{{ c.d }}{% endif %}"),
                         {'a', 'b', 'c'})

    def test_plain_text_broken_and_account_macros(self):
        self.assertEqual(template_variables('plain'), set())
        self.assertEqual(template_variables('{{ a '), set())
        self.assertEqual(template_variables('{{ACCOUNT:x:y}}'), set())


class TestOutcomeTemplates(unittest.TestCase):
    """Outcome fields read from submitted form data"""

    def test_order_labels_and_filter(self):
        data = {
            'list_source': 'service',
            'outcomes-4-folder': '/',
            'outcomes-4-value_template': '{{ b }}',
            'outcomes-1-condition_service': '{{ service }}',
            'outcomes-1-ruleset': 'not a template field',
            'outcomes-1-value_template': '',
        }
        self.assertEqual(outcome_templates(data), [
            ('Outcome 1, Condition Service name', '{{ service }}'),
            ('Outcome 2, Value', '{{ b }}'),
            ('Outcome 2, Folder', '/'),
        ])


class TestDetectDelimiter(unittest.TestCase):
    """The delimiter is read from the header line"""

    def test_tab_from_a_spreadsheet(self):
        self.assertEqual(detect_delimiter('service\tlevel'), '\t')

    def test_semicolon(self):
        self.assertEqual(detect_delimiter('service;level;team'), ';')

    def test_comma(self):
        self.assertEqual(detect_delimiter('service,level'), ',')

    def test_most_frequent_wins(self):
        self.assertEqual(detect_delimiter('a,b;c;d'), ';')

    def test_single_column(self):
        self.assertEqual(detect_delimiter('service'), ',')


class TestParseListSource(unittest.TestCase):
    """parse_list_source"""

    def test_empty(self):
        parsed = parse_list_source('  \n ')
        self.assertEqual((parsed.columns, parsed.rows, parsed.errors),
                         ([], [], []))

    def test_semicolon_list(self):
        parsed = parse_list_source(
            "Service;Service Level\nDisk C:;gold\nCPU load ; silver\n")
        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.delimiter, ';')
        self.assertEqual(parsed.columns, ['service', 'service_level'])
        self.assertEqual(parsed.rows, [
            {'service': 'Disk C:', 'service_level': 'gold'},
            {'service': 'CPU load', 'service_level': 'silver'},
        ])

    def test_tab_list_with_windows_line_ends(self):
        parsed = parse_list_source("service\tteam\r\nMemory\tops\r\n")
        self.assertEqual(parsed.rows, [{'service': 'Memory', 'team': 'ops'}])

    def test_quoted_cell_with_delimiter_and_line_break(self):
        parsed = parse_list_source(
            'service;teams\n"Disk C:";"ops\ndb"\n"CPU; load";ops\n')
        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.rows[0]['teams'], 'ops\ndb')
        self.assertEqual(parsed.rows[1]['service'], 'CPU; load')

    def test_empty_lines_skipped_short_lines_filled(self):
        parsed = parse_list_source("service;level\n\nDisk C:\n;\n")
        self.assertEqual(parsed.rows, [{'service': 'Disk C:', 'level': ''}])

    def test_empty_header_cell_drops_its_column(self):
        # A trailing delimiter in every line is common in exported lists.
        parsed = parse_list_source("service;level;\nDisk C:;gold;\n")
        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.columns, ['service', 'level'])
        self.assertEqual(parsed.rows, [{'service': 'Disk C:', 'level': 'gold'}])

    def test_line_longer_than_header_is_an_error(self):
        parsed = parse_list_source("service;level\nDisk C:;gold;extra\n")
        self.assertEqual(len(parsed.errors), 1)
        self.assertIn('Line 2', parsed.errors[0])

    def test_duplicate_variable_name_is_an_error(self):
        parsed = parse_list_source("Service;service\na;b\n")
        self.assertIn("'service' is used twice", parsed.errors[0])

    def test_header_without_usable_name_is_an_error(self):
        parsed = parse_list_source("--;level\na;b\n")
        self.assertIn('Header column 1', parsed.errors[0])

    def test_too_many_rows(self):
        text = "service\n" + "\n".join(f"s{i}" for i in range(MAX_ROWS + 1))
        self.assertIn('at most', parse_list_source(text).errors[-1])


class TestRowContext(unittest.TestCase):
    """The Jinja context of one row"""

    def test_context(self):
        context = row_context({'service': 'Disk C:'}, 3)
        self.assertEqual(context['service'], 'Disk C:')
        self.assertEqual(context['row'], {'service': 'Disk C:'})
        self.assertEqual(context['row_idx'], 3)
        self.assertIsNone(context['HOSTNAME'])


def _built(value, services=None, **condition):
    rule = {'folder': '/', 'value': value, 'comment': '',
            'description': 'd', 'condition': dict(condition)}
    if services is not None:
        rule['condition']['service_description'] = {
            'match_on': list(services), 'operator': 'one_of'}
    return rule


class TestMergeServiceConditions(unittest.TestCase):
    """Rows only differing in their services become one rule"""

    def test_same_value_joined_in_row_order(self):
        merged = merge_service_conditions([
            _built('10', ['Disk C:']), _built('20', ['Memory']),
            _built('10', ['CPU load']), _built('10', ['Disk C:'])])
        self.assertEqual(len(merged), 2)
        self.assertEqual(
            merged[0]['condition']['service_description']['match_on'],
            ['Disk C:', 'CPU load'])
        self.assertEqual(
            merged[1]['condition']['service_description']['match_on'],
            ['Memory'])

    def test_other_condition_keeps_rules_apart(self):
        merged = merge_service_conditions([
            _built('10', ['Disk C:'], host_name={'match_on': ['srv01']}),
            _built('10', ['Memory'], host_name={'match_on': ['srv02']})])
        self.assertEqual(len(merged), 2)

    def test_rules_without_service_condition_untouched(self):
        rules = [_built('10'), _built('10')]
        self.assertEqual(merge_service_conditions(rules), rules)

    def test_input_lists_not_shared(self):
        first = _built('10', ['Disk C:'])
        source = first['condition']['service_description']['match_on']
        merge_service_conditions([first, _built('10', ['Memory'])])
        self.assertEqual(source, ['Disk C:'])


class _Doc(dict):
    """Embedded outcome stand-in: ``to_mongo`` is all the export reads."""
    def to_mongo(self):
        return dict(self)


def _outcome(**fields):
    outcome = {
        'ruleset': 'extra_service_conf:_ec_sl',
        'folder': '/',
        'folder_index': 0,
        'comment': '',
        'value_template': '{{ level }}',
        'loop_over_list': False,
        'list_to_loop': '',
        'condition_label_template': '',
        'condition_host': '',
        'condition_service': '{{ service }}$',
        'condition_service_label': '',
    }
    outcome.update(fields)
    return _Doc(outcome)


LIST = (
    "Service;Level;Teams\n"
    "Disk C:;10;ops\n"
    "Memory;20;\n"
    "CPU load;10;\"ops,db\"\n"
    "Interface 1;;ops\n"
)


def _list_rule(*outcomes, name='Service levels', text=LIST, source='list'):
    return SimpleNamespace(name=name, rule_source=source, list_source=text,
                           project=None, outcomes=list(outcomes))


@patch('application.plugins.checkmk.helpers.get_list', side_effect=real_get_list)
@patch('application.plugins.checkmk.helpers.render_jinja',
       side_effect=real_render_jinja)
@patch('application.plugins.checkmk.cmk_rules.get_list', side_effect=real_get_list)
@patch('application.plugins.checkmk.cmk_rules.render_jinja',
       side_effect=real_render_jinja)
class TestCalculateListRule(unittest.TestCase):
    """Rendering a list rule once per row"""

    def setUp(self):
        self.sync = make_checkmk_rule_sync()
        self.sync.project = None
        self.sync.log_details = []
        self.sync._ruleset_item_types = {}

    def _rules(self, ruleset='extra_service_conf:_ec_sl'):
        return self.sync.rulsets_by_type.get(ruleset, [])

    def test_rows_with_same_value_are_joined(self, *_mocks):
        self.sync.static_rules = [_list_rule(_outcome())]
        self.sync.calculate_static_rules()

        rules = self._rules()
        self.assertEqual([(r['value'],
                           r['condition']['service_description']['match_on'])
                          for r in rules],
                         [('10', ['Disk C:$', 'CPU load$']),
                          ('20', ['Memory$'])])
        # Owned by the export and named after the Setup Rule, like any
        # other generated rule.
        self.assertEqual(rules[0]['description'],
                         'cmdbsyncer_test_account - Service levels')
        self.assertNotIn('_from_list', rules[0])

    def test_row_with_empty_value_creates_no_rule(self, *_mocks):
        self.sync.static_rules = [_list_rule(_outcome())]
        self.sync.calculate_static_rules()
        services = [name for rule in self._rules() for name in
                    rule['condition']['service_description']['match_on']]
        self.assertNotIn('Interface 1$', services)

    def test_row_with_empty_service_creates_no_rule(self, *_mocks):
        # Without the guard the row would become a rule for every service.
        text = "service;level\n;30\nDisk C:;10\n"
        self.sync.static_rules = [_list_rule(
            _outcome(condition_service='{{ service }}'), text=text)]
        self.sync.calculate_static_rules()
        self.assertEqual([r['value'] for r in self._rules()], ['10'])

    def test_row_with_empty_host_creates_no_rule(self, *_mocks):
        text = "host;level\n;30\nsrv01;10\n"
        self.sync.static_rules = [_list_rule(_outcome(
            condition_service='', condition_host='{{ host }}'), text=text)]
        self.sync.calculate_static_rules()
        rules = self._rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['condition']['host_name']['match_on'],
                         ['srv01'])

    def test_loop_over_a_column(self, *_mocks):
        # A cell holding several entries: one rule per entry, the row stays
        # available next to {{ loop }}. Identical rules collapse.
        outcome = _outcome(
            ruleset='service_contactgroups',
            loop_over_list=True, list_to_loop='teams',
            value_template="'{{ loop }}'", condition_service='',
            condition_service_label='team:{{ loop }}')
        self.sync.static_rules = [_list_rule(outcome)]
        self.sync.calculate_static_rules()
        rules = self._rules('service_contactgroups')
        self.assertEqual([r['value'] for r in rules], ["'ops'", "'db'"])
        self.assertEqual(
            rules[0]['condition']['service_label_groups'][0]['label_group'],
            [{'operator': 'and', 'label': 'team:ops'}])

    def test_whole_row_and_index_available(self, *_mocks):
        outcome = _outcome(value_template="{'svc': '{{ row.service }}', "
                                          "'idx': {{ row_idx }}}",
                           condition_service='{{ service }}')
        self.sync.static_rules = [_list_rule(
            outcome, text="service\nDisk C:\n")]
        self.sync.calculate_static_rules()
        self.assertEqual(self._rules()[0]['value'],
                         "{'svc': 'Disk C:', 'idx': 0}")

    def test_invalid_list_creates_nothing_and_is_reported(self, *_mocks):
        self.sync.static_rules = [_list_rule(
            _outcome(), text="service;level\na;b;c\n")]
        self.sync.calculate_static_rules()
        self.assertEqual(self.sync.rulsets_by_type, {})
        self.assertTrue(any('not valid' in entry[1]
                            for entry in self.sync.log_details))

    def test_host_mode_ignores_the_list(self, *_mocks):
        # Switched back to per host: the left over list is not used, the
        # rule is a plain static rule again (no row variables).
        self.sync.static_rules = [_list_rule(
            _outcome(value_template='5', condition_service='Memory$'),
            source='hosts')]
        self.sync.calculate_static_rules()
        rules = self._rules()
        self.assertEqual([(r['value'],
                           r['condition']['service_description']['match_on'])
                          for r in rules], [('5', ['Memory$'])])

    def test_rule_without_mode_and_with_list_uses_it(self, *_mocks):
        self.sync.static_rules = [_list_rule(_outcome(), source=None)]
        self.sync.calculate_static_rules()
        self.assertEqual(len(self._rules()), 2)

    def test_project_rule_ignores_folder_scope(self, *_mocks):
        self.sync.config = {'settings': {}, 'limit_by_folders': ['/other']}
        rule = _list_rule(_outcome())
        rule.project = 'Team'
        self.sync.static_rules = [rule]
        self.sync.calculate_static_rules()
        self.assertEqual(len(self._rules()), 2)


class _FakeProgress:  # pylint: disable=too-few-public-methods
    """rich.Progress stand-in for the export steps."""
    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def add_task(self, *a, **k):
        return 1

    def advance(self, *a, **k):
        pass


@patch('application.plugins.checkmk.cmk_rules.make_progress', _FakeProgress())
@patch('application.plugins.checkmk.helpers.get_list', side_effect=real_get_list)
@patch('application.plugins.checkmk.helpers.render_jinja',
       side_effect=real_render_jinja)
@patch('application.plugins.checkmk.cmk_rules.get_list', side_effect=real_get_list)
@patch('application.plugins.checkmk.cmk_rules.render_jinja',
       side_effect=real_render_jinja)
class TestListRuleExportDryRun(unittest.TestCase):
    """
    A list rule through ``export_cmk_rules --dry-run``: the rows end up as
    planned Checkmk rules, a row removed from the list as a planned delete,
    and nothing but reads reaches Checkmk.
    """

    def setUp(self):
        self.sync = make_checkmk_rule_sync()
        self.sync.project = None
        self.sync.log_details = []
        self.sync.dry_run = True
        self.sync.dry_run_plan = []
        self.sync._ruleset_item_types = {}
        self.sync._cmk_order_by_ruleset = {}
        self.sync._rule_etag_wildcard_rejected = None
        # No host in the database: only the list rule produces rules.
        hosts = MagicMock()
        hosts.count.return_value = 0
        hosts.__iter__.return_value = iter([])
        self.sync._export_hosts = MagicMock(return_value=hosts)
        self.methods = []

    def _wire(self, cmk_rules):
        def fake_request(url, method='GET', data=None, **_kw):
            self.methods.append(method.upper())
            if method.upper() == 'GET':
                return {'value': cmk_rules}, {'etag': 'x'}
            return {}, {'status_code': 200}
        self.sync.request = MagicMock(side_effect=fake_request)

    @staticmethod
    def _cmk_rule(services, value, rule_id):
        return {
            'id': rule_id,
            'extensions': {
                'folder': '/',
                'value_raw': value,
                'conditions': {
                    'host_tags': [], 'host_label_groups': [],
                    'service_label_groups': [],
                    'service_description': {
                        'match_on': list(services), 'operator': 'one_of'},
                },
                'properties': {
                    'description': 'cmdbsyncer_test_account - Service levels',
                    'comment': '',
                },
            },
        }

    def test_new_list_plans_one_rule_per_value(self, *_mocks):
        self._wire([])
        self.sync.static_rules = [_list_rule(_outcome())]

        self.sync.export_cmk_rules()

        self.assertEqual(set(self.methods), {'GET'})
        planned = [(action, detail) for action, _target, detail
                   in self.sync.dry_run_plan]
        self.assertEqual([action for action, _detail in planned],
                         ['CREATE', 'CREATE'])
        self.assertIn('value: 10', planned[0][1])
        self.assertIn("'Disk C:$', 'CPU load$'", planned[0][1][1])

    def test_unchanged_list_plans_nothing_removed_row_plans_delete(
            self, *_mocks):
        self._wire([
            self._cmk_rule(['Disk C:$', 'CPU load$'], '10', 'r1'),
            self._cmk_rule(['Memory$'], '20', 'r2'),
        ])
        self.sync.static_rules = [_list_rule(_outcome())]
        self.sync.export_cmk_rules()
        self.assertEqual(self.sync.dry_run_plan, [])

        # The row of one service level is gone from the list: its rule is
        # no longer generated and the export plans to remove it.
        self.sync.dry_run_plan = []
        self.sync.rulsets_by_type = {}
        self.sync._rule_signatures = {}
        self.sync.static_rules = [_list_rule(
            _outcome(), text="Service;Level\nDisk C:;10\nCPU load;10\n")]
        self.sync.export_cmk_rules()
        self.assertEqual(
            [(action, target) for action, target, _detail
             in self.sync.dry_run_plan],
            [('DELETE', 'extra_service_conf:_ec_sl r2')])
        self.assertEqual(set(self.methods), {'GET'})


if __name__ == '__main__':
    unittest.main()
