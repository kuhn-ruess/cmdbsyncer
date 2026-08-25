"""
Background runner for the rule optimization analysis.

The analysis is far too slow for a web request, so the page starts it in
a thread and reads state and result from the database.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import os
import sys
import unittest
from datetime import datetime, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from tests import _load_real_module


def _load_runner():
    """Load the runner with its two model imports stubbed."""
    name = 'application.plugins.checkmk.rule_analysis_runner'
    if name in sys.modules:
        return sys.modules[name]
    models = sys.modules.setdefault(
        'application.plugins.checkmk.models',
        ModuleType('application.plugins.checkmk.models'))
    if not hasattr(models, 'CheckmkRuleAnalysis'):
        models.CheckmkRuleAnalysis = MagicMock()
    return _load_real_module(name, os.path.join(
        'plugins', 'checkmk', 'rule_analysis_runner.py'))


class StaleRunTest(unittest.TestCase):
    """
    Nothing supervises the thread. A restarted process leaves the
    document at 'running' forever, so the page has to be able to tell.
    """

    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()

    def _analysis(self, state, minutes_ago):
        return SimpleNamespace(
            state=state,
            started_at=datetime.now() - timedelta(minutes=minutes_ago))

    def test_a_fresh_run_is_not_stale(self):
        self.assertFalse(self.runner.is_stale(self._analysis('running', 5)))

    def test_a_run_that_never_finished_is_stale(self):
        self.assertTrue(self.runner.is_stale(
            self._analysis('running', self.runner.STALE_RUN_MINUTES + 1)))

    def test_a_finished_run_is_never_stale(self):
        self.assertFalse(self.runner.is_stale(
            self._analysis('done', self.runner.STALE_RUN_MINUTES + 1)))

    def test_no_analysis_is_not_stale(self):
        self.assertFalse(self.runner.is_stale(None))


class StartAnalysisTest(unittest.TestCase):
    """Starting a run, and refusing to start a second one."""

    @classmethod
    def setUpClass(cls):
        cls.runner = _load_runner()

    def setUp(self):
        self.thread = patch.object(self.runner, 'threading')
        self.thread_mod = self.thread.start()

    def tearDown(self):
        self.thread.stop()

    def _existing(self, analysis):
        return patch.object(self.runner, 'get_analysis',
                            return_value=analysis)

    def test_a_running_analysis_is_not_started_twice(self):
        running = SimpleNamespace(state='running',
                                  started_at=datetime.now())
        with self._existing(running):
            self.assertIsNone(self.runner.start_analysis())
        self.thread_mod.Thread.assert_not_called()

    def test_a_stale_run_can_be_restarted(self):
        stale = SimpleNamespace(
            pk='id1', state='running', error='', findings=[], min_hosts=10,
            started_at=datetime.now() - timedelta(
                minutes=self.runner.STALE_RUN_MINUTES + 1),
            finished_at=None, save=MagicMock())
        with self._existing(stale):
            self.assertIsNotNone(self.runner.start_analysis())
        self.thread_mod.Thread.return_value.start.assert_called_once()

    def test_starting_resets_the_previous_result(self):
        done = SimpleNamespace(
            pk='id1', state='done', error='boom', findings=[{'old': True}],
            min_hosts=10, started_at=datetime.now(),
            finished_at=datetime.now(), save=MagicMock())
        with self._existing(done):
            analysis = self.runner.start_analysis(min_hosts=42)
        self.assertEqual(analysis.state, 'running')
        self.assertEqual(analysis.findings, [])
        self.assertEqual(analysis.error, '')
        self.assertEqual(analysis.min_hosts, 42)
        self.assertIsNone(analysis.finished_at)
        analysis.save.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
