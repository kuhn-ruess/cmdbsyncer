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
from application.plugins.netbox.rules import NetboxInterfaceRule
from application.plugins.netbox.interfaces import SyncInterfaces
from application.plugins.netbox.ips import SyncIPS
from application.plugins.ansible import playbook_rules
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


@patch.dict(Rule.get_multilist_outcomes.__globals__, render_jinja=real_render_jinja)
class TestNetboxRows(unittest.TestCase):
    """A row describes interfaces and IP addresses of a device by its name"""

    def _syncer(self, cls):
        syncer = cls.__new__(cls)
        syncer.nb = Mock()
        syncer.console = Mock()
        syncer.config = {'name': 'nb'}
        syncer.set_syncer_id = False
        syncer.log_details = []
        syncer.debug = True
        return syncer

    def test_interface_of_a_row(self):
        engine = NetboxInterfaceRule()
        engine.rules = [_rule_doc('if', [
            {'action': 'device', 'param': '{{ HOSTNAME }}', 'list_variable_name': ''},
            {'action': 'name', 'param': '{{ port }}', 'list_variable_name': ''},
            {'action': 'ipv4_addresses', 'param': '{{ ip }}', 'list_variable_name': ''},
        ], 'list', 'hostname;port;ip\nsw01;eth0;10.0.0.1/24\n')]
        row = next(engine.list_rows())
        interface = row.outcomes['interfaces'][0]
        self.assertEqual(row.name, 'sw01')
        self.assertEqual(interface['fields']['name'], {'value': 'eth0'})
        self.assertEqual(interface['sub_fields']['ipv4_addresses'],
                         {'value': ['10.0.0.1/24']})

    def test_new_interface_gets_the_device_id_by_name(self):
        syncer = self._syncer(SyncInterfaces)
        syncer.if_types = ['other']
        syncer.nb.dcim.interfaces.filter.return_value = []
        syncer.nb.dcim.devices.get.return_value = Mock(id=42)
        syncer.nb.dcim.interfaces.create.return_value = Mock(id=7)
        port_infos = []
        syncer.export_interfaces('sw01', [{
            'fields': {'device': {'value': 'sw01'}, 'name': {'value': 'eth0'}},
            'sub_fields': {'ipv4_addresses': {'value': ['10.0.0.1/24']}},
        }], 'dcim', port_infos)
        syncer.nb.dcim.interfaces.filter.assert_called_with(device='sw01', name='eth0')
        syncer.nb.dcim.devices.get.assert_called_with(name='sw01')
        self.assertEqual(syncer.nb.dcim.interfaces.create.call_args[0][0]['device'], 42)
        self.assertEqual(port_infos[0]['netbox_if_id'], 7)

    def test_vm_interface_is_looked_up_on_its_vm(self):
        syncer = self._syncer(SyncInterfaces)
        syncer.if_types = ['other']
        syncer.nb.virtualization.interfaces.filter.return_value = []
        syncer.nb.virtualization.virtual_machines.get.return_value = Mock(id=5)
        syncer.export_interfaces('vm01', [{
            'fields': {'name': {'value': 'eth0'}},
            'sub_fields': {'ipv4_addresses': {'value': ['10.0.0.2/24']}},
        }], 'virtualization', [])
        syncer.nb.virtualization.interfaces.filter.assert_called_with(
            virtual_machine='vm01', name='eth0')
        payload = syncer.nb.virtualization.interfaces.create.call_args[0][0]
        self.assertEqual(payload['virtual_machine'], 5)

    def test_ip_assigned_by_interface_name(self):
        syncer = self._syncer(SyncIPS)
        syncer.nb.dcim.interfaces.get.return_value = Mock(id=7)
        fields = {'assigned_object_id': {'value': 'eth0'}}
        self.assertEqual(syncer.assigned_object_id('sw01', fields), 7)
        syncer.nb.dcim.interfaces.get.assert_called_with(device='sw01', name='eth0')
        self.assertEqual(fields['assigned_object_id'], {'value': '7'})
        self.assertEqual(syncer.assigned_object_id(None, {'assigned_object_id':
                                                           {'value': ' 9 '}}), 9)
        with self.assertRaises(ValueError):
            syncer.assigned_object_id(None, fields | {'assigned_object_id':
                                                      {'value': 'eth0'}})


class TestPlaybookFireRows(unittest.TestCase):
    """A fire rule from a list fires against the host each row names"""

    def test_rows_fire_once_per_named_row(self):
        rule = _rule_doc('fire', [{'playbook': 'site.yml'}], 'list',
                         'hostname\nsrv01\n\nsrv02\n')
        query = Mock()
        query.order_by.return_value = [rule]
        with patch.object(playbook_rules, 'AnsiblePlaybookFireRule') as model, \
                patch.object(playbook_rules, 'Host') as host, \
                patch.object(playbook_rules, 'available_playbooks',
                             return_value=['site.yml']), \
                patch.object(playbook_rules, '_already_fired', return_value=False), \
                patch.object(playbook_rules, 'run_playbook') as run:
            model.objects.return_value = query
            host.get_export_hosts.return_value = []
            self.assertEqual(playbook_rules.fire_playbook_rules(), 2)
        self.assertEqual([call.kwargs['target_host'] for call in run.call_args_list],
                         ['srv01', 'srv02'])


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
