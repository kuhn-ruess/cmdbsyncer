"""
The list source in the rule engine: a list rule never applies to a host,
its rows are rendered on their own (``Rule.list_rows``) and every export
works on them like on a host (``Plugin.list_rows``,
``Plugin.export_list_rows``, ``Plugin.hosts_and_list_rows``).
"""
# pylint: disable=missing-function-docstring,protected-access
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from application.modules.plugin import Plugin
from application.modules.rule.list_source import row_name
from application.modules.rule.rule import Rule
from application.plugins.idoit.rules import IdoitVariableRule
from application.plugins.jira_cloud.rules import JiraExportAttributeRule
from tests import real_render_jinja


class _CollectRule(Rule):
    """Collects the rendered value of every outcome."""

    def add_outcomes(self, rule, rule_outcomes, outcomes):
        for outcome in rule_outcomes:
            outcomes.setdefault('values', []).append(
                (rule['name'], outcome['value'].format(**self.attributes)))
        return outcomes


def _rule_doc(name, outcomes, rule_source=None, list_source=None):
    """A rule document as the engine reads it."""
    doc = SimpleNamespace(name=name, rule_source=rule_source, list_source=list_source)
    doc.to_mongo = lambda: {
        'name': name, '_id': name, 'condition_typ': 'anyway', 'conditions': [],
        'outcomes': outcomes, 'last_match': False,
    }
    return doc


class TestRowName(unittest.TestCase):
    """The object a row stands for"""

    def test_hostname_wins_over_name(self):
        self.assertEqual(row_name({'hostname': 'srv01', 'name': 'x'}), 'srv01')

    def test_name_column(self):
        self.assertEqual(row_name({'name': 'srv02'}), 'srv02')

    def test_none(self):
        self.assertIsNone(row_name({'hostname': '', 'site': 'a'}))


class TestRuleListRows(unittest.TestCase):
    """Rule.list_rows and the host path"""

    def setUp(self):
        self.engine = _CollectRule()
        self.engine.rules = [
            _rule_doc('per host', [{'value': 'host {HOSTNAME}'}]),
            _rule_doc('from list', [{'value': '{level} for {HOSTNAME}'}],
                      'list', 'Hostname;Level\nsrv01;gold\nsrv02;silver\n'),
        ]

    def test_a_list_rule_never_applies_to_a_host(self):
        self.engine.attributes = {'HOSTNAME': 'web01'}
        outcomes = self.engine.check_rules('web01')
        self.assertEqual(outcomes, {'values': [('per host', 'host web01')]})

    def test_rows_are_rendered_on_their_own(self):
        rows = list(self.engine.list_rows({'site': 'a'}))
        self.assertEqual([row.name for row in rows], ['srv01', 'srv02'])
        self.assertEqual(rows[0].outcomes,
                         {'values': [('from list', 'gold for srv01')]})
        self.assertEqual(rows[1].attributes['all']['site'], 'a')
        self.assertEqual(rows[1].attributes['all']['row_idx'], 1)
        self.assertEqual(rows[1].attributes['filtered'],
                         {'hostname': 'srv02', 'level': 'silver'})
        self.assertEqual(rows[0].rule, 'from list')
        self.assertEqual(self.engine.list_errors, [])

    def test_a_broken_list_creates_no_row(self):
        self.engine.rules = [_rule_doc('broken', [{'value': 'x'}], 'list',
                                       'a;b\n1;2;3\n')]
        self.assertEqual(list(self.engine.list_rows()), [])
        self.assertIn("List rule 'broken' skipped", self.engine.list_errors[0])

    def test_a_legacy_rule_with_a_list_counts_as_list_rule(self):
        self.engine.rules = [_rule_doc('legacy', [{'value': '{level}'}], None,
                                       'level\ngold\n')]
        self.assertEqual(self.engine.check_rules('web01'), {})
        self.assertEqual(len(list(self.engine.list_rows())), 1)


# The engines' own module globals: another test may load a second copy of
# a rules module under the same name.
@patch.dict(IdoitVariableRule.add_outcomes.__globals__, render_jinja=real_render_jinja)
@patch.dict(JiraExportAttributeRule.add_outcomes.__globals__, render_jinja=real_render_jinja)
class TestRuleTypes(unittest.TestCase):
    """Rule types render a row like a host"""

    def test_idoit_object_of_a_row(self):
        engine = IdoitVariableRule()
        engine.rules = [_rule_doc('idoit', [
            {'action': 'id_object_description', 'param': '{{ HOSTNAME }} in {{ room }}'},
            {'action': 'id_category', 'param': "{'C__CATG__LOCATION': {'room': '{{ room }}'}}"},
        ], 'list', 'name;room\nsrv01;R1\n')]
        row = next(engine.list_rows())
        self.assertEqual(row.outcomes['description'], 'srv01 in R1')
        self.assertEqual(row.outcomes['id_category'],
                         {'C__CATG__LOCATION': {'room': 'R1'}})

    def test_jira_fields_of_a_row(self):
        engine = JiraExportAttributeRule()
        engine.rules = [_rule_doc('jira', [
            {'target': '7|Owner', 'value': '{{ owner }}'},
        ], 'list', 'hostname,owner\nsrv01,team-a\n')]
        row = next(engine.list_rows())
        self.assertEqual(row.outcomes, {'fields_by_type': {'7': {'Owner': 'team-a'}}})


class TestPluginListRows(unittest.TestCase):
    """The export side"""

    def setUp(self):
        with patch('application.modules.plugin.atexit'):
            self.plugin = Plugin()
        self.plugin.log_details = []
        self.plugin.debug = False
        self.plugin.actions = _CollectRule()
        self.plugin.actions.rules = [
            _rule_doc('per host', [{'value': 'host {HOSTNAME}'}]),
            _rule_doc('from list', [{'value': '{level}'}], 'list',
                      'name;level\nsrv01;gold\n;silver\n'),
        ]

    def test_named_rows_need_a_name(self):
        with patch('builtins.print'):
            rows = list(self.plugin.list_rows(named=True))
        self.assertEqual([row.name for row in rows], ['srv01'])
        self.assertIn("row 2 skipped", self.plugin.log_details[-1][1])

    def test_a_failing_row_does_not_stop_the_others(self):
        seen = []

        def export(row):
            seen.append(row.row_idx)
            if row.row_idx == 0:
                raise ValueError('rejected')

        with patch('builtins.print'), patch('application.modules.plugin.logger'):
            self.plugin.export_list_rows(export)
        self.assertEqual(seen, [0, 1])
        self.assertIn(('export_error srv01', 'rejected'), self.plugin.log_details)

    def test_hosts_then_rows(self):
        db_host = Mock(hostname='web01', cache={})
        attributes = {'all': {'HOSTNAME': 'web01'}, 'filtered': {}}
        self.plugin.get_attributes = Mock(return_value=attributes)
        self.plugin.get_host_data = Mock(return_value={'from': 'host'})
        items = list(self.plugin.hosts_and_list_rows([db_host], 'cache'))
        self.assertEqual(items[0], ('web01', attributes, {'from': 'host'}))
        self.assertEqual([item[0] for item in items[1:]],
                         ['srv01', 'from list, row 2'])
        self.assertEqual(items[1][2], {'values': [('from list', 'gold')]})


if __name__ == '__main__':
    unittest.main()
