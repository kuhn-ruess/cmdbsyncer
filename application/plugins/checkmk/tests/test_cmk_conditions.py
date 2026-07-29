"""
Unit tests for the Checkmk Setup-rule label conditions: the parse_label
helper and how build_condition_and_update_rule_params turns the Host/Service
label condition fields into Checkmk condition structures (and skips + logs a
malformed one instead of crashing or silently dropping the rule).
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import patch

from application.plugins.checkmk.cmk_rules import (
    parse_label,
    label_condition_problems,
)
from tests import make_checkmk_rule_sync

# Reused patch targets — render passes templates through verbatim, get_list
# splits on commas like the real helper does.
_RENDER = patch('application.plugins.checkmk.cmk_rules.render_jinja',
                side_effect=lambda tpl, **kw: tpl)
_GET_LIST = patch('application.plugins.checkmk.cmk_rules.get_list',
                  side_effect=lambda v: [x.strip() for x in v.split(',') if x.strip()])


class TestParseLabel(unittest.TestCase):
    """Tests for the parse_label helper"""

    def test_simple(self):
        self.assertEqual(parse_label('env:prod'), ('env', 'prod'))

    def test_strips_whitespace(self):
        self.assertEqual(parse_label('  env : prod '), ('env', 'prod'))

    def test_value_may_contain_colons(self):
        self.assertEqual(
            parse_label('url:https://example.com'),
            ('url', 'https://example.com'))

    def test_missing_colon_is_none(self):
        self.assertIsNone(parse_label('noseparator'))

    def test_empty_half_is_none(self):
        self.assertIsNone(parse_label('key:'))
        self.assertIsNone(parse_label(':value'))

    def test_empty_input_is_none(self):
        self.assertIsNone(parse_label(''))
        self.assertIsNone(parse_label(None))


class TestLabelConditionProblems(unittest.TestCase):
    """Static save-time validation of the label condition fields"""

    def test_empty_is_fine(self):
        self.assertEqual(label_condition_problems('', ''), [])

    def test_valid_static_host_label(self):
        self.assertEqual(label_condition_problems(host_label='env:prod'), [])

    def test_jinja_host_label_is_trusted(self):
        # Value from Jinja, single label, no literal comma — accepted.
        self.assertEqual(label_condition_problems(host_label='env:{{value}}'), [])

    def test_host_label_literal_comma_rejected_even_with_jinja(self):
        # The reported case: Jinja slipped it past the old check, but the
        # literal comma means "two labels", which a Host label does not allow.
        problems = label_condition_problems(host_label='test:{{value}},test')
        self.assertEqual(len(problems), 1)
        self.assertIn('single', problems[0])
        self.assertIn('comma', problems[0])

    def test_host_label_static_without_colon_rejected(self):
        problems = label_condition_problems(host_label='justkey')
        self.assertEqual(len(problems), 1)
        self.assertIn("'key:value'", problems[0])

    def test_service_label_multiple_valid(self):
        self.assertEqual(
            label_condition_problems(service_label='crit:yes, team:db'), [])

    def test_service_label_static_bad_entry_rejected(self):
        problems = label_condition_problems(service_label='crit:yes, bogus')
        self.assertEqual(len(problems), 1)
        self.assertIn('bogus', problems[0])

    def test_service_label_bad_entry_rejected_with_jinja_sibling(self):
        # The reported value read as a Service label: 'test' has no colon.
        problems = label_condition_problems(service_label='test:{{value}},test')
        self.assertEqual(len(problems), 1)
        self.assertIn("'test'", problems[0])

    def test_service_label_jinja_with_inner_comma_not_flagged(self):
        # A comma inside a Jinja expression must not be split into a bogus
        # literal entry.
        self.assertEqual(
            label_condition_problems(service_label="{{ ','.join(x) }}"), [])


class TestBuildConditionLabels(unittest.TestCase):
    """Label-condition handling in build_condition_and_update_rule_params"""

    def setUp(self):
        self.sync = make_checkmk_rule_sync()

    def _build(self, **conditions):
        """Run build_condition for one host with the given condition fields."""
        rule_params = {'value_template': "{'k': 'v'}", 'folder': '/', **conditions}
        return self.sync.build_condition_and_update_rule_params(
            rule_params, {'all': {'HOSTNAME': 'host1'}})

    def _assert_skipped(self, result, needle):
        """Rule was dropped (None) and an ERROR mentioning needle was logged."""
        self.assertIsNone(result)
        self.assertTrue(any(
            d[0] == 'ERROR' and needle in d[1] for d in self.sync.log_details))

    @_RENDER
    def test_host_label_keeps_colon_in_value(self, _render):
        # A value with its own colon (e.g. a URL) must not break — only the
        # first colon separates key from value.
        result = self._build(condition_label_template='url:https://example.com')
        label = result['condition']['host_label_groups'][0]['label_group'][0]['label']
        self.assertEqual(label, 'url:https://example.com')

    @_RENDER
    def test_host_label_malformed_skips_and_logs(self, _render):
        self._assert_skipped(
            self._build(condition_label_template='no_colon_here'), 'Host label')

    @_GET_LIST
    @_RENDER
    def test_service_label_and_combines(self, _render, _get_list):
        result = self._build(condition_service_label='crit:yes, team:db')
        group = result['condition']['service_label_groups'][0]['label_group']
        self.assertEqual(
            [entry['label'] for entry in group], ['crit:yes', 'team:db'])

    @_GET_LIST
    @_RENDER
    def test_service_label_malformed_skips_and_logs(self, _render, _get_list):
        self._assert_skipped(
            self._build(condition_service_label='crit:yes, bogus'), 'Service label')


if __name__ == '__main__':
    unittest.main()
