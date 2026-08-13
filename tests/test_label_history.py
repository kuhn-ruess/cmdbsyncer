"""
Tests for the label history settings and its cleanup helpers.

The module is loaded from source (the package `application` is stubbed
in tests/__init__.py) so the pure functions can be exercised without a
live MongoDB.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

from tests import _load_real_module  # pylint: disable=no-name-in-module

# Loaded under its own name so the stub the other tests rely on stays in
# place; the module itself only needs the stubbed `application.app`.
label_history = _load_real_module(
    'application.helpers.label_history_under_test',
    os.path.join('helpers', 'label_history.py'),
)


class RetentionTest(unittest.TestCase):
    """LABEL_HISTORY_RETENTION_DAYS handling."""

    def setUp(self):
        self.config = label_history.app.config
        self._saved = dict(self.config)

    def tearDown(self):
        self.config.clear()
        self.config.update(self._saved)

    def test_default_when_unset(self):
        """An installation without the key gets the documented default."""
        self.config.pop('LABEL_HISTORY_RETENTION_DAYS', None)
        self.assertEqual(label_history.label_history_retention_days(),
                         label_history.DEFAULT_RETENTION_DAYS)

    def test_seconds_match_days(self):
        """The TTL index gets the retention expressed in seconds."""
        self.config['LABEL_HISTORY_RETENTION_DAYS'] = 30
        self.assertEqual(label_history.label_history_retention_seconds(),
                         30 * 86400)

    def test_zero_is_clamped(self):
        """
        0 must never reach the TTL index: MongoDB reads it as "expire at
        changed_at", which would wipe the history as it is written.
        """
        self.config['LABEL_HISTORY_RETENTION_DAYS'] = 0
        self.assertEqual(label_history.label_history_retention_days(), 1)

    def test_garbage_falls_back(self):
        """A non-numeric value must not break the model definition."""
        self.config['LABEL_HISTORY_RETENTION_DAYS'] = 'ninety'
        self.assertEqual(label_history.label_history_retention_days(),
                         label_history.DEFAULT_RETENTION_DAYS)

    def test_recording_is_off_by_default(self):
        """Nothing is written unless the installation opts in."""
        self.config.pop('LABEL_HISTORY_ENABLED', None)
        self.assertFalse(label_history.label_history_enabled())


class RegistryTest(unittest.TestCase):
    """Policies registered by the models."""

    def setUp(self):
        self.retention = sys.modules['application.helpers.retention']

    def test_register_is_idempotent(self):
        """
        Re-importing a model module must not queue a second policy for
        the same collection.
        """
        # pylint: disable=protected-access
        before = list(self.retention._POLICIES)
        doc = type('Doc', (), {})
        self.retention.register_retention('probe', doc, 'ts', 'PROBE_DAYS', 7)
        self.retention.register_retention('probe', doc, 'ts', 'PROBE_DAYS', 9)
        names = [entry[0] for entry in self.retention._POLICIES]
        try:
            self.assertEqual(names.count('probe'), 1)
            self.assertEqual(self.retention._POLICIES[-1][4], 9)
        finally:
            self.retention._POLICIES[:] = before


class PipelineTest(unittest.TestCase):
    """The analysis has to read both collection layouts."""

    def test_legacy_reads_the_top_level_key(self):
        """Legacy documents carry one label key each."""
        stages = label_history._key_pipeline(  # pylint: disable=protected-access
            label_history.LEGACY_COLLECTION)
        self.assertEqual(stages, [{'$project': {'key': '$key',
                                                'host': '$host'}}])

    def test_events_are_unwound(self):
        """An event carries many labels, so it has to be unwound first."""
        stages = label_history._key_pipeline(  # pylint: disable=protected-access
            'host_label_event')
        self.assertEqual(stages[0], {'$unwind': '$changes'})
        self.assertEqual(stages[1]['$project']['key'], '$changes.key')


class CutoffTest(unittest.TestCase):
    """Retention boundary used by the purge."""

    def test_cutoff_lies_in_the_past(self):
        """A retention of N days cuts N days back from now."""
        cutoff = label_history.cutoff_for(7)
        expected = datetime.utcnow() - timedelta(days=7)
        self.assertLess(abs((cutoff - expected).total_seconds()), 5)


if __name__ == '__main__':
    unittest.main()
