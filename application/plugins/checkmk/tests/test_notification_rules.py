"""
Unit tests for checkmk notification_rules module.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access,unused-argument
import ast
import unittest
from unittest.mock import patch

import jinja2

from application.plugins.checkmk.notification_rules import (
    CheckmkNotificationRuleSync,
    HOST_EVENT_FLAGS,
    SERVICE_EVENT_FLAGS,
    _canonical,
    _split_csv,
    _split_kv_list,
    _split_range,
    _split_tag_list,
)
from application.plugins.checkmk.cmk2 import CmkException
from tests import base_mock_init


def _real_get_list(value):
    """The shared test bootstrap stubs syncer_jinja, get_list included.
    Stand in for it with the same behaviour the real helper has for the
    shapes a loop list arrives in: a list, a list literal, or a comma
    separated string."""
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return [entry.strip() for entry in value.split(',') if entry.strip()]


def _real_render(template, **context):
    """The shared test bootstrap stubs render_jinja with a MagicMock —
    rendering tests need actual Jinja substitution, so route through a
    real Jinja2 environment in this test module only. The Syncer's own
    Jinja helpers are offered the same way the real environment does."""
    context.setdefault('get_list', _real_get_list)
    return jinja2.Template(template).render(**context)


def _make_outcome(**overrides):
    """Build an outcome dict with sensible defaults for rendering."""
    outcome = {
        'notification_method': 'mail',
        'multiply_by_list': False,
        'multiply_list': '',
        'contact_group_recipients': '{{cmk_contact_group}}_ALARM',
        'match_contact_groups': '{{cmk_contact_group}}',
        'match_host_groups': '',
        'match_service_groups': '',
        'match_sites': '',
        'match_folder': '',
        'match_hosts': '',
        'match_exclude_hosts': '',
        'match_services': '',
        'match_exclude_services': '',
        'match_host_labels': '',
        'match_service_labels': '',
        'match_host_tags': '',
        'match_check_types': '',
        'match_plugin_output': '',
        'match_only_during_time_period': '',
        'match_service_levels': '',
        'match_contacts': '',
        'match_host_event_types': ['up_down', 'up_unreachable'],
        'match_service_event_types': [],
        'disable_rule': False,
    }
    outcome.update(overrides)
    return outcome


class TestSplitCsv(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_split_csv(''), [])
        self.assertEqual(_split_csv(None), [])

    def test_strip_and_split(self):
        self.assertEqual(_split_csv('a, b ,c'), ['a', 'b', 'c'])

    def test_drops_blanks(self):
        self.assertEqual(_split_csv('a,, b ,'), ['a', 'b'])


class TestSplitKvList(unittest.TestCase):
    def test_pairs(self):
        self.assertEqual(
            _split_kv_list('env:prod, role:db'),
            [{'key': 'env', 'value': 'prod'},
             {'key': 'role', 'value': 'db'}])

    def test_skips_malformed(self):
        self.assertEqual(_split_kv_list('env:prod, broken'),
                         [{'key': 'env', 'value': 'prod'}])

    def test_value_with_colon(self):
        self.assertEqual(
            _split_kv_list('label:a:b'),
            [{'key': 'label', 'value': 'a:b'}])

    def test_empty(self):
        self.assertEqual(_split_kv_list(''), [])


class TestSplitTagList(unittest.TestCase):
    def test_pairs(self):
        self.assertEqual(
            _split_tag_list('criticality:prod'),
            [{'tag_type': 'tag_group', 'tag_group': 'criticality',
              'operator': 'is', 'tag_id': 'prod'}])


class TestSplitRange(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(_split_range('0,3'),
                         {'from_level': 0, 'to_level': 3})

    def test_invalid(self):
        self.assertIsNone(_split_range('a,b'))
        self.assertIsNone(_split_range('1'))
        self.assertIsNone(_split_range(''))


class TestCanonical(unittest.TestCase):
    def test_dict_order_independent(self):
        self.assertEqual(
            _canonical({'b': 1, 'a': 2}),
            _canonical({'a': 2, 'b': 1}),
        )

    def test_lists_preserve_order(self):
        self.assertNotEqual(
            _canonical([1, 2, 3]),
            _canonical([3, 2, 1]),
        )


class TestEventFlagSets(unittest.TestCase):
    def test_known_flags_present(self):
        self.assertIn('up_down', HOST_EVENT_FLAGS)
        self.assertIn('ok_crit', SERVICE_EVENT_FLAGS)


def _cfg(recipients, plugin='mail'):
    """Minimal rule_config in the shape Checkmk stores it."""
    return {
        'rule_properties': {
            'description': 'cmdbsyncer_test_account - DO NOT EDIT',
            'do_not_apply_this_rule': {'state': 'disabled'},
        },
        'notification_method': {
            'notify_plugin': {
                'option': 'create_notification_with_the_following_parameters',
                'plugin_params': {'plugin_name': plugin},
            },
            'notification_bulking': {'state': 'disabled'},
        },
        'contact_selection': {
            'members_of_contact_groups': {
                'state': 'enabled', 'value': list(recipients)},
        },
        'conditions': {},
    }


class _SyncTestCase(unittest.TestCase):
    """Bootstrap a sync class instance without touching Checkmk."""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param, checkmk_version='2.4.0p1')

        self.init_patcher = patch(
            'application.plugins.checkmk.notification_rules.CMK2.__init__',
            mock_init)
        self.init_patcher.start()
        self.sync = CheckmkNotificationRuleSync()

    def tearDown(self):
        self.init_patcher.stop()

    def _apply(self, desired, existing):
        """Run the diff with all three apply calls captured."""
        created, updated, deleted = [], [], []
        with patch.object(self.sync, '_create_rule',
                          side_effect=created.append), \
             patch.object(self.sync, '_update_rule',
                          side_effect=lambda cmk, body: updated.append((cmk, body))), \
             patch.object(self.sync, '_delete_rule',
                          side_effect=deleted.append):
            self.sync._diff_and_apply(desired, existing)
        return created, updated, deleted


class TestCheckmkNotificationRuleSync(_SyncTestCase):
    """Render / build / diff logic on the sync class."""

    def test_event_dict_filters_unknown_and_fills_defaults(self):
        result = self.sync._event_dict(
            ['up_down', 'NONSENSE'], HOST_EVENT_FLAGS)
        # Every known flag must be present; only the selected one True.
        self.assertEqual(set(result.keys()), set(HOST_EVENT_FLAGS))
        self.assertTrue(result['up_down'])
        self.assertFalse(result['down_up'])
        self.assertNotIn('NONSENSE', result)

    def test_event_dict_empty_returns_all_false(self):
        result = self.sync._event_dict([], HOST_EVENT_FLAGS)
        self.assertEqual(set(result.keys()), set(HOST_EVENT_FLAGS))
        self.assertFalse(any(result.values()))

    def test_render_rule_returns_none_without_recipients(self):
        outcome = _make_outcome(contact_group_recipients='')
        with patch(
                'application.plugins.checkmk.notification_rules.render_jinja',
                side_effect=_real_render):
            body = self.sync._render_rule(
                outcome, {'cmk_contact_group': 'ops'},
                'cmdbsyncer_42 - DO NOT EDIT')
        self.assertIsNone(body)

    def test_render_rule_renders_jinja(self):
        outcome = _make_outcome()
        with patch(
                'application.plugins.checkmk.notification_rules.render_jinja',
                side_effect=_real_render):
            body = self.sync._render_rule(
                outcome, {'cmk_contact_group': 'ops'},
                'cmdbsyncer_42 - DO NOT EDIT')
        self.assertIsNotNone(body)
        cfg = body['rule_config']
        # rule_properties block carries the marker now (CMK 2.4 schema).
        self.assertEqual(cfg['rule_properties']['description'],
                         'cmdbsyncer_42 - DO NOT EDIT')
        self.assertEqual(cfg['rule_properties']['comment'], '')
        self.assertEqual(cfg['rule_properties']['do_not_apply_this_rule'],
                         {'state': 'disabled'})
        # contact_selection: every slot present, only members_of_contact_groups enabled.
        self.assertEqual(
            cfg['contact_selection']['members_of_contact_groups'],
            {'state': 'enabled', 'value': ['ops_ALARM']})
        self.assertEqual(
            cfg['contact_selection']['all_users'], {'state': 'disabled'})
        # conditions: every slot present, only the configured ones enabled.
        self.assertEqual(
            cfg['conditions']['match_contact_groups'],
            {'state': 'enabled', 'value': ['ops']})
        self.assertEqual(
            cfg['conditions']['match_host_groups'], {'state': 'disabled'})
        host_events = cfg['conditions']['match_host_event_type']
        self.assertEqual(host_events['state'], 'enabled')
        self.assertTrue(host_events['value']['up_down'])
        self.assertTrue(host_events['value']['up_unreachable'])
        self.assertFalse(host_events['value']['down_up'])
        self.assertEqual(
            cfg['conditions']['match_service_event_type'],
            {'state': 'disabled'})
        # notification_method has bulking slot.
        self.assertEqual(
            cfg['notification_method']['notification_bulking'],
            {'state': 'disabled'})

    def test_render_rule_with_all_match_fields(self):
        # Override the default CG-match template to empty so this test
        # focuses on the other 12+ match fields without tripping the
        # "empty CG match" skip guard.
        outcome = _make_outcome(
            match_contact_groups='',
            contact_group_recipients='static_alarm_group',
            match_sites='siteA, siteB',
            match_folder='/it/linux',
            match_hosts='host1, host2',
            match_exclude_hosts='excluded',
            match_services='Filesystem .*',
            match_exclude_services='Boring',
            match_host_labels='env:prod, role:db',
            match_service_labels='kind:disk',
            match_host_tags='criticality:prod',
            match_check_types='df, mem',
            match_plugin_output='WARNING.*disk',
            match_only_during_time_period='workhours',
            match_service_levels='1,3',
            match_contacts='alice, bob',
        )
        with patch(
                'application.plugins.checkmk.notification_rules.render_jinja',
                side_effect=_real_render):
            body = self.sync._render_rule(
                outcome, {}, 'cmdbsyncer_42 - DO NOT EDIT')
        cfg = body['rule_config']
        cnd = cfg['conditions']

        self.assertEqual(cnd['match_sites'],
                         {'state': 'enabled', 'value': ['siteA', 'siteB']})
        self.assertEqual(cnd['match_folder'],
                         {'state': 'enabled', 'value': '/it/linux'})
        self.assertEqual(cnd['match_hosts'],
                         {'state': 'enabled', 'value': ['host1', 'host2']})
        self.assertEqual(cnd['match_exclude_hosts'],
                         {'state': 'enabled', 'value': ['excluded']})
        self.assertEqual(cnd['match_services'],
                         {'state': 'enabled', 'value': ['Filesystem .*']})
        self.assertEqual(cnd['match_exclude_services'],
                         {'state': 'enabled', 'value': ['Boring']})
        self.assertEqual(
            cnd['match_host_labels'],
            {'state': 'enabled',
             'value': [{'key': 'env', 'value': 'prod'},
                       {'key': 'role', 'value': 'db'}]})
        self.assertEqual(
            cnd['match_service_labels'],
            {'state': 'enabled',
             'value': [{'key': 'kind', 'value': 'disk'}]})
        self.assertEqual(
            cnd['match_host_tags'],
            {'state': 'enabled',
             'value': [{'tag_type': 'tag_group', 'tag_group': 'criticality',
                        'operator': 'is', 'tag_id': 'prod'}]})
        self.assertEqual(cnd['match_check_types'],
                         {'state': 'enabled', 'value': ['df', 'mem']})
        self.assertEqual(cnd['match_plugin_output'],
                         {'state': 'enabled', 'value': 'WARNING.*disk'})
        self.assertEqual(cnd['match_only_during_time_period'],
                         {'state': 'enabled', 'value': 'workhours'})
        self.assertEqual(
            cnd['match_service_levels'],
            {'state': 'enabled',
             'value': {'from_level': 1, 'to_level': 3}})
        self.assertEqual(cnd['match_contacts'],
                         {'state': 'enabled', 'value': ['alice', 'bob']})

    def test_render_rule_dedup_identical_bodies(self):
        outcome = _make_outcome()
        with patch(
                'application.plugins.checkmk.notification_rules.render_jinja',
                side_effect=_real_render):
            body1 = self.sync._render_rule(
                outcome, {'cmk_contact_group': 'ops'},
                'cmdbsyncer_42 - DO NOT EDIT')
            body2 = self.sync._render_rule(
                outcome, {'cmk_contact_group': 'ops'},
                'cmdbsyncer_42 - DO NOT EDIT')
        self.assertEqual(_canonical(body1['rule_config']),
                         _canonical(body2['rule_config']))

    def test_event_types_accept_lists_directly(self):
        """ListField from the model arrives as a Python list, not CSV."""
        outcome = _make_outcome(
            match_service_event_types=['ok_warn', 'warn_crit', 'BOGUS'])
        with patch(
                'application.plugins.checkmk.notification_rules.render_jinja',
                side_effect=_real_render):
            body = self.sync._render_rule(
                outcome, {'cmk_contact_group': 'ops'},
                'cmdbsyncer_42 - DO NOT EDIT')
        cfg = body['rule_config']
        svc = cfg['conditions']['match_service_event_type']
        self.assertEqual(svc['state'], 'enabled')
        self.assertTrue(svc['value']['ok_warn'])
        self.assertTrue(svc['value']['warn_crit'])
        self.assertFalse(svc['value']['ok_crit'])
        self.assertNotIn('BOGUS', svc['value'])

    def test_render_rule_skips_empty_match_contact_group(self):
        """When the admin set a CG-match template but the host's label
        is empty, the rule must not be created — otherwise we'd match
        every host with no CG and ship to a `_ALARM`-only recipient."""
        outcome = _make_outcome(
            match_contact_groups='{{anwendung_kontaktgruppe}}',
            contact_group_recipients='{{anwendung_kontaktgruppe}}_ALARM',
        )
        with patch(
                'application.plugins.checkmk.notification_rules.render_jinja',
                side_effect=_real_render):
            body = self.sync._render_rule(
                outcome, {'anwendung_kontaktgruppe': ''},
                'cmdbsyncer_42 - DO NOT EDIT')
        self.assertIsNone(body)

    def test_export_rejects_unsupported_version(self):
        self.sync.checkmk_version = '2.3.0p1'
        with self.assertRaises(CmkException):
            self.sync.export_notification_rules()

    def test_fetch_existing_filters_by_marker(self):
        def _entry(rule_id, description):
            return {
                'id': rule_id,
                'extensions': {
                    'rule_config': {
                        'rule_properties': {'description': description},
                    },
                },
            }
        cmk_payload = {
            'value': [
                _entry('mine-1', 'cmdbsyncer_test_account - DO NOT EDIT'),
                _entry('foreign-1', 'Hand-crafted by an admin'),
                _entry('other-account', 'cmdbsyncer_other - DO NOT EDIT'),
            ],
        }
        with patch.object(self.sync, 'request',
                          return_value=(cmk_payload, {})):
            result = self.sync._fetch_existing_rules('cmdbsyncer_test_account')
        ids = [r['id'] for r in result]
        self.assertEqual(ids, ['mine-1'])

    def test_diff_creates_new_and_deletes_orphan(self):
        desired = [
            {'rule_config': _cfg(['ops'])},
            {'rule_config': _cfg(['dba'])},
        ]
        existing = [
            {'id': 'keep-id', 'rule_config': _cfg(['ops'])},
            {'id': 'orphan-id', 'rule_config': _cfg(['legacy'])},
        ]

        created, updated, deleted = self._apply(desired, existing)

        self.assertEqual(deleted, ['orphan-id'])
        self.assertEqual(updated, [])
        self.assertEqual(len(created), 1)
        self.assertEqual(
            self.sync._recipients(created[0]['rule_config']), ('dba',))

    def test_dry_run_sends_nothing(self):
        """A dry run computes the same diff but keeps its hands off CMK."""
        self.sync.dry_run = True
        created, updated, deleted = self._apply(
            [{'rule_config': _cfg(['ops'])}, {'rule_config': _cfg(['dba'])}],
            [{'id': 'orphan-id', 'rule_config': _cfg(['legacy'])}])

        self.assertEqual((created, updated, deleted), ([], [], []))

    def test_diff_keeps_rule_whose_method_the_admin_configured(self):
        """
        The admin tuned the notification method of one of our rules in
        Checkmk. Those parameters are theirs — the rule must be left
        alone instead of being recreated with our bare plugin name.
        """
        admin_cfg = _cfg(['ops'])
        admin_cfg['notification_method']['notify_plugin']['plugin_params'].update({
            'from_details': {'state': 'enabled',
                             'value': {'address': 'admin@example.com'}},
        })
        admin_cfg['notification_method']['notification_bulking'] = {
            'state': 'enabled', 'value': {'time_horizon': 60}}

        created, updated, deleted = self._apply(
            [{'rule_config': _cfg(['ops'])}],
            [{'id': 'tuned-id', 'rule_config': admin_cfg}])

        self.assertEqual((created, updated, deleted), ([], [], []))

    def test_diff_updates_in_place_instead_of_recreating(self):
        """
        Content of a rule changed. It is rewritten in place so the
        notification method settings stay attached to it — a delete +
        create would reset them to Checkmk's first parameter set.
        """
        stored_cfg = _cfg(['ops'])
        stored_cfg['conditions']['match_folder'] = {'state': 'disabled'}
        desired_cfg = _cfg(['ops'])
        desired_cfg['conditions']['match_folder'] = {
            'state': 'enabled', 'value': '/it'}

        created, updated, deleted = self._apply(
            [{'rule_config': desired_cfg}],
            [{'id': 'edit-id', 'rule_config': stored_cfg}])

        self.assertEqual((created, deleted), ([], []))
        self.assertEqual([cmk['id'] for cmk, _body in updated], ['edit-id'])

    def test_diff_detects_admin_edit_via_body_compare(self):
        """
        Admin changed one of our fields on a rule in Checkmk. The body
        compare no longer matches, so the rule is rewritten with our
        state — in place, keeping its notification method.
        """
        admin_edited_cfg = _cfg(['ops'])
        admin_edited_cfg['rule_properties']['do_not_apply_this_rule'] = {
            'state': 'enabled'}

        created, updated, deleted = self._apply(
            [{'rule_config': _cfg(['ops'])}],
            [{'id': 'edited-id', 'rule_config': admin_edited_cfg}])

        self.assertEqual((created, deleted), ([], []))
        self.assertEqual(len(updated), 1)
        self.assertEqual(
            updated[0][1]['rule_config']['rule_properties']['do_not_apply_this_rule'],
            {'state': 'disabled'})

    def test_update_rule_keeps_checkmk_notification_method(self):
        stored_cfg = _cfg(['ops'])
        stored_cfg['notification_method']['notify_plugin']['plugin_params'].update({
            'from_details': {'state': 'enabled',
                             'value': {'address': 'admin@example.com'}},
        })
        sent = []
        with patch.object(self.sync, 'request',
                          side_effect=lambda *a, **kw: sent.append((a, kw)) or ({}, {})):
            self.sync._update_rule({'id': 'rule-id', 'rule_config': stored_cfg},
                                   {'rule_config': _cfg(['ops'])})
        (url,), kwargs = sent[0]
        self.assertEqual(url, '/objects/notification_rule/rule-id')
        self.assertEqual(kwargs['method'], 'PUT')
        self.assertEqual(
            kwargs['data']['rule_config']['notification_method'],
            stored_cfg['notification_method'])

    def test_update_rule_pushes_own_method_when_plugin_changed(self):
        stored_cfg = _cfg(['ops'], plugin='slack')
        desired_cfg = _cfg(['ops'], plugin='mail')
        sent = []
        with patch.object(self.sync, 'request',
                          side_effect=lambda *a, **kw: sent.append((a, kw)) or ({}, {})):
            self.sync._update_rule({'id': 'rule-id', 'rule_config': stored_cfg},
                                   {'rule_config': desired_cfg})
        _args, kwargs = sent[0]
        self.assertEqual(
            kwargs['data']['rule_config']['notification_method'],
            desired_cfg['notification_method'])


class TestNotificationRuleLoop(_SyncTestCase):
    """One rule per entry of a list instead of one rule per host."""

    def test_loop_disabled_renders_one_rule(self):
        outcome = _make_outcome()
        with patch(
                'application.plugins.checkmk.notification_rules.render_jinja',
                side_effect=_real_render), \
             patch('application.plugins.checkmk.notification_rules.get_list',
                   side_effect=_real_get_list):
            bodies = self.sync._render_outcome(
                outcome, {'cmk_contact_group': 'ops'},
                'cmdbsyncer_42 - DO NOT EDIT')
        self.assertEqual(len(bodies), 1)

    def test_loop_builds_one_rule_per_list_entry(self):
        """
        One attribute holding several contact groups becomes one rule
        per group, with the entry available to every field as {{name}}.
        """
        outcome = _make_outcome(
            multiply_by_list=True,
            multiply_list='{{get_list(anwendung_kontaktgruppe)|safe}}',
            match_contact_groups='{{name}}',
            contact_group_recipients=(
                "gro00_cmk_alarm_sms_{{name|replace('grr00_', '')}}, "
                "gro00_cmk_alarm_email_{{name|replace('grr00_', '')}}"),
        )
        with patch(
                'application.plugins.checkmk.notification_rules.render_jinja',
                side_effect=_real_render), \
             patch('application.plugins.checkmk.notification_rules.get_list',
                   side_effect=_real_get_list):
            bodies = self.sync._render_outcome(
                outcome,
                {'anwendung_kontaktgruppe': 'grr00_oracle,grr00_sap'},
                'cmdbsyncer_42 - DO NOT EDIT')

        self.assertEqual(len(bodies), 2)
        first, second = (b['rule_config'] for b in bodies)
        self.assertEqual(first['conditions']['match_contact_groups'],
                         {'state': 'enabled', 'value': ['grr00_oracle']})
        self.assertEqual(
            first['contact_selection']['members_of_contact_groups'],
            {'state': 'enabled',
             'value': ['gro00_cmk_alarm_sms_oracle',
                       'gro00_cmk_alarm_email_oracle']})
        self.assertEqual(second['conditions']['match_contact_groups'],
                         {'state': 'enabled', 'value': ['grr00_sap']})
        self.assertEqual(
            second['contact_selection']['members_of_contact_groups'],
            {'state': 'enabled',
             'value': ['gro00_cmk_alarm_sms_sap',
                       'gro00_cmk_alarm_email_sap']})

    def test_loop_over_python_list_attribute(self):
        outcome = _make_outcome(
            multiply_by_list=True,
            multiply_list='{{get_list(groups)|safe}}',
            match_contact_groups='{{name}}',
            contact_group_recipients='{{name}}_ALARM',
        )
        with patch(
                'application.plugins.checkmk.notification_rules.render_jinja',
                side_effect=_real_render), \
             patch('application.plugins.checkmk.notification_rules.get_list',
                   side_effect=_real_get_list):
            bodies = self.sync._render_outcome(
                outcome, {'groups': ['db', 'web']},
                'cmdbsyncer_42 - DO NOT EDIT')
        self.assertEqual(
            [b['rule_config']['conditions']['match_contact_groups']['value']
             for b in bodies],
            [['db'], ['web']])

    def test_loop_over_empty_list_renders_nothing(self):
        outcome = _make_outcome(
            multiply_by_list=True,
            multiply_list='{{get_list(groups)|safe}}',
            match_contact_groups='{{name}}',
        )
        with patch(
                'application.plugins.checkmk.notification_rules.render_jinja',
                side_effect=_real_render), \
             patch('application.plugins.checkmk.notification_rules.get_list',
                   side_effect=_real_get_list):
            bodies = self.sync._render_outcome(
                outcome, {'groups': ''}, 'cmdbsyncer_42 - DO NOT EDIT')
        self.assertEqual(bodies, [])

if __name__ == '__main__':
    unittest.main()
