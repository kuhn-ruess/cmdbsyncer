"""
Unit tests for the Event Driven Ansible rules and sender
"""
# pylint: disable=missing-function-docstring,protected-access
import unittest
from unittest.mock import Mock, patch

from jinja2 import Environment

from application.plugins.eda import rules as eda_rules
from application.plugins.eda import sender as eda_sender
from application.plugins.eda.rules import EdaEventRuleEngine, render_extra_vars
from application.plugins.eda.sender import EdaSender, build_payload


def _render(value, replace_newlines=True, _ctx=None, **_kwargs):
    """Real Jinja instead of the stub, keeping the newline switch."""
    if replace_newlines:
        value = value.replace('\n', '')
    return Environment().from_string(value).render(**(_ctx or {})).strip()


def setUpModule():  # pylint: disable=invalid-name
    """Render templates for real"""
    patcher = patch.object(eda_rules, 'render_jinja', _render)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def _event(**overrides):
    """One collected event as the rule engine produces it."""
    return {'rule_id': 'r1', 'rule_name': 'Register TLS', 'event': 'register_agent_tls',
            'resend_after_hours': 24, 'vars': {'site': 'main'}, 'error': None} | overrides


def _sender(**config):
    """A sender with a config but without a database or connection."""
    instance = EdaSender.__new__(EdaSender)
    instance.config = {'address': 'https://eda.example.com/hook'} | config
    instance.account_name = 'eda'
    instance.dry_run = False
    instance.log_details = []
    instance.counts = {'sent': 0, 'failed': 0, 'skipped': 0}
    return instance


class TestExtraVars(unittest.TestCase):
    """The YAML of an outcome"""

    def test_yaml_rendered_with_host_attributes(self):
        self.assertEqual(render_extra_vars('site: "{{ site }}"\nport: 8000',
                                           {'site': 'main'}),
                         {'site': 'main', 'port': 8000})

    def test_empty_means_no_vars(self):
        self.assertEqual(render_extra_vars('', {}), {})
        self.assertEqual(render_extra_vars(None, {}), {})

    def test_no_mapping_is_an_error(self):
        with self.assertRaises(ValueError):
            render_extra_vars('- a\n- b', {})
        with self.assertRaises(ValueError):
            render_extra_vars('a: [', {})


class TestRuleEngine(unittest.TestCase):
    """Matching rules turn into events"""

    def test_one_event_per_outcome(self):
        engine = EdaEventRuleEngine()
        engine.attributes = {'HOSTNAME': 'srv01', 'site': 'main'}
        rule = {'_id': 'abc', 'name': 'Register'}
        outcomes = engine.add_outcomes(rule, [
            {'event': 'register_agent_tls', 'extra_vars': 'site: "{{ site }}"'},
            {'event': 'register_{{ "bakery" }}', 'resend_after_hours': 0},
            {'event': ''},
        ], {})
        events = outcomes['events']
        self.assertEqual([e['event'] for e in events],
                         ['register_agent_tls', 'register_bakery'])
        self.assertEqual(events[0]['vars'], {'site': 'main'})
        self.assertEqual(events[0]['resend_after_hours'], 24)
        self.assertEqual(events[1]['resend_after_hours'], 0)
        self.assertEqual(events[0]['rule_id'], 'abc')

    def test_broken_vars_become_an_error(self):
        engine = EdaEventRuleEngine()
        engine.attributes = {}
        outcomes = engine.add_outcomes({'_id': 'x', 'name': 'n'},
                                       [{'event': 'e', 'extra_vars': '- list'}], {})
        self.assertTrue(outcomes['events'][0]['error'])


class TestAuth(unittest.TestCase):
    """How the account authenticates against the event stream"""

    def test_token_with_prefix(self):
        headers, auth = _sender(password='s3cret', auth_prefix='Bearer').auth()
        self.assertEqual(headers, {'Authorization': 'Bearer s3cret'})
        self.assertIsNone(auth)

    def test_bare_token_in_own_header(self):
        headers, _ = _sender(password='s3cret', auth_header='X-Token',
                             auth_prefix='').auth()
        self.assertEqual(headers, {'X-Token': 's3cret'})

    def test_basic_auth_with_username(self):
        headers, auth = _sender(username='eda', password='pw').auth()
        self.assertEqual(headers, {})
        self.assertEqual(auth, ('eda', 'pw'))

    def test_no_credentials(self):
        self.assertEqual(_sender().auth(), ({}, None))


class TestSend(unittest.TestCase):
    """Sending, dedup and the history"""

    def test_payload(self):
        payload = build_payload('srv01', _event())
        self.assertEqual(payload['event'], 'register_agent_tls')
        self.assertEqual(payload['hostname'], 'srv01')
        self.assertEqual(payload['vars'], {'site': 'main'})
        self.assertEqual(payload['source'], 'cmdbsyncer')

    def test_sent_and_logged(self):
        instance = _sender(password='t')
        instance.inner_request = Mock(return_value=Mock(status_code=200, text='ok'))
        with patch.object(eda_sender, 'EdaEventLog') as log, patch('builtins.print'):
            log.objects.return_value.first.return_value = None
            instance.handle_event('srv01', _event())
        self.assertEqual(instance.counts['sent'], 1)
        kwargs = instance.inner_request.call_args.kwargs
        self.assertEqual(kwargs['json']['hostname'], 'srv01')
        # No prefix field on the account: the default Bearer
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer t')
        self.assertEqual(log.call_args.kwargs['status'], 'success')

    def test_recently_sent_is_skipped(self):
        instance = _sender()
        instance.inner_request = Mock()
        with patch.object(eda_sender, 'EdaEventLog') as log:
            log.objects.return_value.first.return_value = object()
            instance.handle_event('srv01', _event())
        instance.inner_request.assert_not_called()
        self.assertEqual(instance.counts['skipped'], 1)
        self.assertIn('sent_at__gte', log.objects.call_args.kwargs)

    def test_resend_zero_means_only_once(self):
        instance = _sender()
        with patch.object(eda_sender, 'EdaEventLog') as log:
            log.objects.return_value.first.return_value = None
            instance.recently_sent('srv01', _event(resend_after_hours=0))
        self.assertNotIn('sent_at__gte', log.objects.call_args.kwargs)

    def test_failure_is_logged(self):
        instance = _sender()
        instance.inner_request = Mock(return_value=Mock(status_code=401, text='denied'))
        with patch.object(eda_sender, 'EdaEventLog') as log, patch('builtins.print'):
            log.objects.return_value.first.return_value = None
            instance.handle_event('srv01', _event())
        self.assertEqual(instance.counts['failed'], 1)
        self.assertEqual(log.call_args.kwargs['status'], 'failure')
        self.assertEqual(log.call_args.kwargs['http_status'], 401)

    def test_broken_vars_are_not_sent(self):
        instance = _sender()
        instance.inner_request = Mock()
        with patch.object(eda_sender, 'EdaEventLog') as log, patch('builtins.print'):
            log.objects.return_value.first.return_value = None
            instance.handle_event('srv01', _event(error='bad yaml'))
        instance.inner_request.assert_not_called()
        self.assertEqual(log.call_args.kwargs['response'], 'bad yaml')

    def test_dry_run_sends_and_logs_nothing(self):
        instance = _sender()
        instance.dry_run = True
        instance.inner_request = Mock()
        with patch.object(eda_sender, 'EdaEventLog') as log, patch('builtins.print'):
            log.objects.return_value.first.return_value = None
            instance.handle_event('srv01', _event())
        instance.inner_request.assert_not_called()
        log.assert_not_called()
