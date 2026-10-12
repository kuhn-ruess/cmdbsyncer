"""
Unit tests for checkmk dcd module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import unittest
from unittest.mock import Mock, patch

from types import SimpleNamespace

from jinja2.exceptions import UndefinedError
from application.plugins.checkmk.dcd import CheckmkDCDRuleSync
from tests import base_mock_init, real_render_jinja


class TestCheckmkDCDRuleSync(unittest.TestCase):
    """Tests for CheckmkDCDRuleSync"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param,
                           console=Mock(), all_rules=[], debug=False)

        self.init_patcher = patch(
            'application.plugins.checkmk.dcd.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.sync = CheckmkDCDRuleSync()

    def tearDown(self):
        self.init_patcher.stop()

    def test_does_rule_exist_true(self):
        with patch.object(self.sync, 'request',
                          return_value=({'id': 'rule1'}, {})):
            self.assertTrue(self.sync.does_rule_exist('rule1'))

    def test_does_rule_exist_false(self):
        with patch.object(self.sync, 'request', return_value=({}, {})):
            self.assertFalse(self.sync.does_rule_exist('rule1'))

    def test_build_timeranges(self):
        rule = {
            'exclude_time_ranges': [
                {'start_hour': 11, 'start_minute': 0,
                 'end_hour': 13, 'end_minute': 30},
                {'start_hour': 22, 'start_minute': 5,
                 'end_hour': 6, 'end_minute': 0},
            ]
        }
        result = self.sync.build_timeranges(rule)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {'start': '11:00', 'end': '13:30'})
        self.assertEqual(result[1], {'start': '22:05', 'end': '6:00'})

    def test_build_timeranges_empty(self):
        rule = {'exclude_time_ranges': []}
        result = self.sync.build_timeranges(rule)
        self.assertEqual(result, [])

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_build_creation_rules(self, mock_render):
        mock_render.side_effect = lambda tpl, *args, **kw: tpl
        rule = {
            'creation_rules': [
                {
                    'folder_path': '/test',
                    'delete_hosts': False,
                    'host_attributes': [
                        {'attribute_name': 'tag_agent', 'attribute_value': 'no-agent'}
                    ],
                    'host_filters': ['lx1'],
                },
            ]
        }
        result = self.sync.build_creation_rules(rule, {})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['folder_path'], '/test')
        self.assertEqual(result[0]['host_attributes'], {'tag_agent': 'no-agent'})
        self.assertEqual(result[0]['host_filters'], ['lx1'])

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_build_creation_rules_no_filters(self, mock_render):
        mock_render.side_effect = lambda tpl, *args, **kw: tpl
        rule = {
            'creation_rules': [
                {
                    'folder_path': '/test',
                    'delete_hosts': True,
                    'host_attributes': [],
                    'host_filters': [],
                },
            ]
        }
        result = self.sync.build_creation_rules(rule, {})
        self.assertNotIn('host_filters', result[0])

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_build_rule_payload(self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl

        rule = {
            'dcd_id': 'dcd1',
            'title': 'Test DCD',
            'comment': 'A comment',
            'disabled': False,
            'site': 'site1',
            'connector_type': 'piggyback',
            'restricted_source_hosts': [],
            'interval': '60',
            'creation_rules': [],
            'activate_changes_interval': '300',
            'discover_on_creation': True,
            'exclude_time_ranges': [],
            'no_deletion_time_after_init': '120',
            'max_cache_age': '3600',
            'validity_period': '60',
            'documentation_url': '',
        }

        result = self.sync.build_rule_payload(rule, {})
        self.assertEqual(result['dcd_id'], 'dcd1')
        self.assertEqual(result['title'], 'Test DCD')
        self.assertNotIn('documentation_url', result)

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_build_rule_payload_with_doc_url(self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl

        rule = {
            'dcd_id': 'dcd1',
            'title': 'Test',
            'comment': '',
            'disabled': False,
            'site': 'site1',
            'connector_type': 'piggyback',
            'restricted_source_hosts': [],
            'interval': '60',
            'creation_rules': [],
            'activate_changes_interval': '300',
            'discover_on_creation': True,
            'exclude_time_ranges': [],
            'no_deletion_time_after_init': '120',
            'max_cache_age': '3600',
            'validity_period': '60',
            'documentation_url': 'https://docs.example.com',
        }

        result = self.sync.build_rule_payload(rule, {})
        self.assertEqual(result['documentation_url'], 'https://docs.example.com')

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_build_rule_payload_undefined_returns_empty(self, mock_render):
        mock_render.side_effect = UndefinedError("var")

        rule = {
            'dcd_id': '{{ undefined }}',
            'title': 'Test',
            'comment': '',
            'disabled': False,
            'site': 'site1',
            'connector_type': 'piggyback',
            'restricted_source_hosts': [],
            'interval': '60',
            'creation_rules': [],
            'activate_changes_interval': '300',
            'discover_on_creation': True,
            'exclude_time_ranges': [],
            'no_deletion_time_after_init': '120',
            'max_cache_age': '3600',
            'validity_period': '60',
            'documentation_url': '',
        }

        result = self.sync.build_rule_payload(rule, {})
        self.assertEqual(result, {})

    def _payload_rule(self):
        return {
            'dcd_id': 'dcd1', 'title': 'T', 'comment': '', 'disabled': False,
            'site': 'site1', 'connector_type': 'piggyback',
            'restricted_source_hosts': [], 'interval': '60',
            'creation_rules': [], 'activate_changes_interval': '300',
            'discover_on_creation': True, 'exclude_time_ranges': [],
            'no_deletion_time_after_init': '120', 'max_cache_age': '3600',
            'validity_period': '60', 'documentation_url': '',
        }

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_payload_nests_connector_on_24plus(self, mock_render):
        # Checkmk 2.4+ wants the connector settings nested under "connector"
        # and no longer accepts the two 2.3-only fields.
        mock_render.side_effect = lambda tpl, **kw: tpl
        self.sync.checkmk_version = '2.4.0p19.cee'
        result = self.sync.build_rule_payload(self._payload_rule(), {})
        self.assertIn('connector', result)
        self.assertNotIn('connector_type', result)  # not at top level
        conn = result['connector']
        self.assertEqual(conn['connector_type'], 'piggyback')
        self.assertIn('interval', conn)
        self.assertNotIn('activate_changes_interval', conn)
        self.assertNotIn('exclude_time_ranges', conn)

    @patch('application.plugins.checkmk.dcd.render_jinja')
    def test_payload_connector_keeps_23_fields(self, mock_render):
        mock_render.side_effect = lambda tpl, **kw: tpl
        self.sync.checkmk_version = '2.3.0p48.cce'
        conn = self.sync.build_rule_payload(self._payload_rule(), {})['connector']
        self.assertIn('activate_changes_interval', conn)
        self.assertIn('exclude_time_ranges', conn)

    def test_account_site(self):
        self.sync.config = {'address': 'http://host:8080/cmk/'}
        self.assertEqual(self.sync._account_site(), 'cmk')
        self.sync.config = {'address': 'https://mon.example.com/prod'}
        self.assertEqual(self.sync._account_site(), 'prod')
        self.sync.config = {'address': ''}
        self.assertEqual(self.sync._account_site(), '')

    def test_account_context_exposes_fields_without_secrets(self):
        self.sync.config = {
            'name': 'prod', 'address': 'http://h/cmk', 'username': 'auto',
            'my_field': 'x', 'password': 'secret',
            'bakery_passphrase': 'p', '_id': 1,
        }
        ctx = self.sync._account_context()
        # custom + standard fields are exposed
        self.assertEqual(ctx['name'], 'prod')
        self.assertEqual(ctx['my_field'], 'x')
        # secrets / internal ids are withheld
        for hidden in ('password', 'bakery_passphrase', '_id'):
            self.assertNotIn(hidden, ctx)

    def test_create_rule_in_cmk(self):
        with patch.object(self.sync, 'request') as mock_req:
            mock_req.return_value = (None, {})
            self.sync.create_rule_in_cmk({'dcd_id': 'test1'})

        mock_req.assert_called_once()
        self.assertEqual(mock_req.call_args[1]['method'], 'POST')

    def test_calculate_rules_of_host_adds_unique(self):
        with patch.object(self.sync, 'build_rule_payload',
                          return_value={'dcd_id': 'r1'}):
            self.sync.calculate_rules_of_host(
                'host1', {'type1': [{'rule': 'data'}]}, {})

        self.assertEqual(len(self.sync.all_rules), 1)

    def test_calculate_rules_of_host_skips_empty(self):
        with patch.object(self.sync, 'build_rule_payload', return_value={}):
            self.sync.calculate_rules_of_host(
                'host1', {'type1': [{'rule': 'data'}]}, {})

        self.assertEqual(len(self.sync.all_rules), 0)

    def test_calculate_rules_of_host_no_duplicates(self):
        payload = {'dcd_id': 'r1'}
        with patch.object(self.sync, 'build_rule_payload', return_value=payload):
            self.sync.calculate_rules_of_host(
                'host1', {'type1': [{'rule': '1'}, {'rule': '2'}]}, {})

        self.assertEqual(len(self.sync.all_rules), 1)

    def test_calculate_rules_of_host_skips_connection_without_id(self):
        with patch.object(self.sync, 'build_rule_payload',
                          return_value={'dcd_id': '', 'title': 't'}):
            self.sync.calculate_rules_of_host(
                'host1', {'type1': [{'rule': 'data'}]}, {})

        self.assertEqual(self.sync.all_rules, [])


class _Doc(dict):
    """Embedded outcome stand-in: ``to_mongo`` is all the export reads."""
    def to_mongo(self):
        return dict(self)


def _dcd_outcome(**fields):
    outcome = {
        'dcd_id': '{{ id }}', 'title': 'Piggyback {{ id }}', 'comment': '',
        'documentation_url': '', 'disabled': False, 'site': '{{ cmk_site }}',
        'connector_type': 'piggyback', 'restricted_source_hosts': [],
        'interval': 60, 'creation_rules': [], 'activate_changes_interval': 600,
        'discover_on_creation': False, 'exclude_time_ranges': [],
        'no_deletion_time_after_init': 6000, 'max_cache_age': 3600,
        'validity_period': 60,
    }
    outcome.update(fields)
    return _Doc(outcome)


def _dcd_rule(text, source='list', **outcome):
    return SimpleNamespace(name='dc list', rule_source=source,
                           list_source=text, outcomes=[_dcd_outcome(**outcome)])


def _render(value, *args, **kwargs):
    """Real Jinja for the export; the int settings are rendered as text."""
    return real_render_jinja(str(value), *args, **kwargs)


@patch('application.plugins.checkmk.dcd.render_jinja', side_effect=_render)
class TestDCDListRule(unittest.TestCase):
    """A DCD rule rendered once per row of its pasted list"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param,
                           console=Mock(), all_rules=[], debug=False)

        with patch('application.plugins.checkmk.dcd.CMK2.__init__', mock_init):
            self.sync = CheckmkDCDRuleSync()
        self.sync.version_at_least = Mock(return_value=True)

    def _ids(self):
        return [(rule['dcd_id'], rule['title'], rule['site'])
                for rule in self.sync.all_rules]

    def test_one_connection_per_row(self, _render):
        self.sync.static_rules = [_dcd_rule("ID\ndc1\ndc2\ndc1\n\n")]
        self.sync.calculate_static_rules({'cmk_site': 'site_a', 'account': {}})
        # The repeated row creates its connection once
        self.assertEqual(self._ids(), [('dc1', 'Piggyback dc1', 'site_a'),
                                       ('dc2', 'Piggyback dc2', 'site_a')])

    def test_columns_override_nothing_but_add_variables(self, _render):
        self.sync.static_rules = [_dcd_rule(
            "id;site\ndc1;site_b\n", site='{{ site }}')]
        self.sync.calculate_static_rules({'cmk_site': 'site_a', 'account': {}})
        self.assertEqual(self._ids(), [('dc1', 'Piggyback dc1', 'site_b')])

    def test_row_without_id_creates_nothing(self, _render):
        self.sync.static_rules = [_dcd_rule("id;title\n;x\ndc2;y\n")]
        self.sync.calculate_static_rules({'cmk_site': 'site_a', 'account': {}})
        self.assertEqual([rule['dcd_id'] for rule in self.sync.all_rules],
                         ['dc2'])

    def test_invalid_list_creates_nothing_and_is_reported(self, _render):
        self.sync.static_rules = [_dcd_rule("id;site\ndc1;a;extra\n")]
        self.sync.calculate_static_rules({'cmk_site': 'site_a', 'account': {}})
        self.assertEqual(self.sync.all_rules, [])
        self.assertIn("List rule 'dc list' skipped",
                      self.sync.log_details[-1][1])

    def test_host_mode_renders_once_and_ignores_the_list(self, _render):
        self.sync.static_rules = [_dcd_rule("id\ndc1\ndc2\n", source='hosts',
                                            dcd_id='static_dc')]
        self.sync.calculate_static_rules({'cmk_site': 'site_a', 'account': {}})
        self.assertEqual([rule['dcd_id'] for rule in self.sync.all_rules],
                         ['static_dc'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
