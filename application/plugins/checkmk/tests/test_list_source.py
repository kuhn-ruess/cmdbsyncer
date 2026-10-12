"""
Tests for the List Source of Checkmk Setup Rules: the merge of service
conditions, the per-row rendering and the export (dry run) path. The parser
itself is tested in ``tests/test_list_source.py``.
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from application.plugins.checkmk.list_source import merge_service_conditions
from tests import make_checkmk_rule_sync, real_get_list, real_render_jinja


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
