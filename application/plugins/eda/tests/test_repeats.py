"""
Unit tests for the detection of events that repeat without effect
"""
# pylint: disable=missing-function-docstring
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from application.plugins.eda import repeats
from application.plugins.eda import sender as eda_sender
from application.plugins.eda.repeats import (
    collect_summary, note_match, note_send, repeat_threshold, summarize,
)
from application.plugins.eda.sender import EdaSender

NOW = datetime(2026, 10, 13, 6, 0, 0)


def _state(**values):
    """A streak as the model holds it."""
    base = {'account': 'eda', 'rule_id': 'r1', 'rule_name': 'Register TLS',
            'hostname': 'srv01', 'event': 'register_agent_tls', 'state': 'pending',
            'sends': 0, 'failures': 0, 'total_sends': 0, 'repeat_threshold': 3,
            'first_sent': None, 'last_sent': None, 'last_status': None,
            'last_http_status': None, 'last_match': None, 'resolved_at': None}
    return SimpleNamespace(**(base | values))


class TestThreshold(unittest.TestCase):
    """The account field"""

    def test_default_and_values(self):
        self.assertEqual(repeat_threshold(None), 3)
        self.assertEqual(repeat_threshold(''), 3)
        self.assertEqual(repeat_threshold('5'), 5)
        self.assertEqual(repeat_threshold('0'), 0)
        self.assertEqual(repeat_threshold('-2'), 0)
        self.assertEqual(repeat_threshold('many'), 3)


class TestStreak(unittest.TestCase):
    """Counting sends while a host keeps matching"""

    def test_repeating_from_threshold_on(self):
        state = _state()
        for _ in range(2):
            note_match(state, 'Register TLS', 3, NOW)
            note_send(state, True, 200, NOW)
        self.assertEqual(state.state, 'pending')
        note_match(state, 'Register TLS', 3, NOW)
        note_send(state, False, 500, NOW)
        self.assertEqual(state.state, 'repeating')
        self.assertEqual((state.sends, state.failures, state.total_sends), (3, 1, 3))
        self.assertEqual(state.last_status, 'failure')
        self.assertEqual(state.first_sent, NOW)

    def test_threshold_zero_never_repeats(self):
        state = _state(sends=50)
        note_match(state, 'Register TLS', 0, NOW)
        self.assertEqual(state.state, 'pending')

    def test_resolved_streak_starts_over(self):
        state = _state(sends=7, failures=2, total_sends=7, first_sent=NOW,
                       resolved_at=NOW, state='resolved')
        note_match(state, 'Register TLS', 3, NOW)
        self.assertIsNone(state.resolved_at)
        self.assertEqual((state.sends, state.failures, state.total_sends), (0, 0, 7))
        self.assertIsNone(state.first_sent)
        self.assertEqual(state.state, 'pending')


class TestSummary(unittest.TestCase):
    """What the API and with it Checkmk gets"""

    def test_counts_and_offenders(self):
        states = [
            _state(hostname='srv01', sends=5, last_status='success'),
            _state(hostname='srv01', event='register_agent_bakery', sends=3,
                   last_status='failure', failures=3),
            _state(hostname='srv02', sends=1, last_status='failure'),
            _state(account='other', hostname='srv03', sends=4, repeat_threshold=10),
        ]
        result = summarize(states, {'eda': (12, 4)})
        self.assertEqual(result['repeating'], 2)
        self.assertEqual(result['repeating_hosts'], 1)
        self.assertEqual(result['pending'], 2)
        self.assertEqual(result['failing'], 2)
        self.assertEqual(result['max_sends'], 5)
        self.assertEqual(result['events_24h'], 12)
        self.assertEqual(result['failed_24h'], 4)
        self.assertEqual([a['account'] for a in result['accounts']], ['eda', 'other'])
        eda = result['accounts'][0]
        self.assertEqual((eda['repeating'], eda['repeating_hosts'], eda['pending']), (2, 1, 1))
        self.assertEqual([o['sends'] for o in result['offenders']], [5, 3])
        self.assertEqual(result['offenders'][0]['threshold'], 3)
        self.assertFalse(result['offenders_truncated'])

    def test_min_sends_overrides_and_limit(self):
        states = [_state(hostname=f'srv{i}', sends=i) for i in range(1, 6)]
        result = summarize(states, {}, min_sends=2, limit=2)
        self.assertEqual(result['repeating'], 4)
        self.assertEqual(result['min_sends'], 2)
        self.assertEqual([o['hostname'] for o in result['offenders']], ['srv5', 'srv4'])
        self.assertTrue(result['offenders_truncated'])

    def test_nothing_sent(self):
        result = summarize([], {})
        self.assertEqual(result['repeating'], 0)
        self.assertEqual(result['accounts'], [])
        self.assertEqual(result['offenders'], [])

    def test_collect_applies_account_and_scope(self):
        states = [_state(hostname='srv01', sends=4), _state(hostname='srv02', sends=4)]
        logs = MagicMock()
        logs.distinct.side_effect = lambda field: {'hostname': ['srv01', 'srv02'],
                                                   'account': ['eda']}[field]
        logs.filter.return_value = logs
        logs.count.return_value = 2
        with patch.object(repeats, 'EdaEventState') as state_cls, \
                patch.object(repeats, 'EdaEventLog') as log_cls:
            state_cls.objects.return_value = states
            log_cls.objects.return_value = logs
            result = collect_summary(account='eda',
                                     hostname_filter=lambda names: {'srv01'} & names)
        self.assertEqual(state_cls.objects.call_args.kwargs['account'], 'eda')
        self.assertEqual(log_cls.objects.call_args.kwargs['account'], 'eda')
        self.assertEqual([o['hostname'] for o in result['offenders']], ['srv01'])
        logs.filter.assert_any_call(hostname__in=['srv01'])


def _sender(**config):
    """A sender with a config but without a database or connection."""
    instance = EdaSender.__new__(EdaSender)
    instance.config = {'address': 'https://eda.example.com/hook'} | config
    instance.account_name = 'eda'
    instance.dry_run = False
    instance.log_details = []
    instance.counts = {'sent': 0, 'failed': 0, 'skipped': 0}
    instance.run_started = NOW
    return instance


def _event():
    return {'rule_id': 'r1', 'rule_name': 'Register TLS', 'event': 'register_agent_tls',
            'resend_after_hours': 24, 'vars': {}, 'error': None}


class TestSenderTracking(unittest.TestCase):
    """The sender keeps the streaks up to date"""

    def test_send_counts_in_the_streak(self):
        state = _state()
        instance = _sender(repeat_threshold='1')
        instance.inner_request = Mock(return_value=Mock(status_code=200, text='ok'))
        with patch.object(eda_sender, 'EdaEventLog') as log, \
                patch.object(eda_sender, 'EdaEventState') as state_cls, \
                patch('builtins.print'):
            log.objects.return_value.first.return_value = None
            state_cls.objects.return_value.first.return_value = state
            state.save = Mock()
            instance.handle_event('srv01', _event())
        self.assertEqual(state.sends, 1)
        self.assertEqual(state.state, 'repeating')
        self.assertEqual(state.save.call_count, 2)

    def test_skipped_event_still_matches(self):
        state = _state(sends=2, last_match=None)
        state.save = Mock()
        instance = _sender()
        instance.inner_request = Mock()
        with patch.object(eda_sender, 'EdaEventLog') as log, \
                patch.object(eda_sender, 'EdaEventState') as state_cls:
            log.objects.return_value.first.return_value = object()
            state_cls.objects.return_value.first.return_value = state
            instance.handle_event('srv01', _event())
        self.assertEqual(state.sends, 2)
        self.assertIsNotNone(state.last_match)

    def test_dry_run_tracks_nothing(self):
        instance = _sender()
        instance.dry_run = True
        with patch.object(eda_sender, 'EdaEventLog') as log, \
                patch.object(eda_sender, 'EdaEventState') as state_cls, \
                patch('builtins.print'):
            log.objects.return_value.first.return_value = None
            instance.handle_event('srv01', _event())
        state_cls.objects.assert_not_called()

    def test_unmatched_streaks_are_resolved(self):
        instance = _sender()
        with patch.object(eda_sender, 'EdaEventState') as state_cls:
            state_cls.objects.return_value.update.return_value = 2
            self.assertEqual(instance.resolve_unmatched(), 2)
        kwargs = state_cls.objects.call_args.kwargs
        self.assertEqual(kwargs['last_match__lt'], NOW)
        self.assertIsNone(kwargs['resolved_at'])
        self.assertEqual(state_cls.objects.return_value.update.call_args.kwargs['set__state'],
                         'resolved')


if __name__ == '__main__':
    unittest.main()
