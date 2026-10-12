"""
Tests for the List Source of a rule: the rule source switch, the parser,
the check on save and the Jinja context of a row. Shared by every rule type
that can take a pasted list (Checkmk Setup Rules and DCD rules).
"""
# pylint: disable=missing-function-docstring
import unittest
from types import SimpleNamespace

from application.modules.rule.list_source import (
    check_list_rule,
    column_name,
    detect_delimiter,
    is_list_rule,
    outcome_templates,
    parse_list_source,
    row_context,
    rule_uses_list,
    template_variables,
    MAX_ROWS,
)


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

    def test_rule_document(self):
        self.assertTrue(is_list_rule(
            SimpleNamespace(rule_source='list', list_source='a\n1')))
        # Rule types without the fields are never list rules.
        self.assertFalse(is_list_rule(SimpleNamespace()))


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
            "renders empty. Columns: "
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
        fields = (('value_template', 'Value'), ('folder', 'Folder'),
                  ('condition_service', 'Condition Service name'))
        self.assertEqual(outcome_templates(data, fields), [
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


if __name__ == '__main__':
    unittest.main()
