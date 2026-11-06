"""
The small helpers several modules share
"""
import unittest
from unittest.mock import MagicMock, patch

from application.helpers.queue_worker import QueueWorker
from application.modules.plugin import Plugin


class TestQueueWorker(unittest.TestCase):
    """QueueWorker"""

    @staticmethod
    def _started(unfinished_tasks):
        worker = QueueWorker(MagicMock(unfinished_tasks=unfinished_tasks), 'test-worker', 30)
        worker.start(lambda: None)
        return worker

    def test_starts_once(self):
        """A second start doesn't start another thread."""
        calls = []
        worker = QueueWorker(MagicMock(), 'test-worker', 30)
        with patch('application.helpers.queue_worker.threading.Thread') as thread:
            worker.start(calls.append)
            worker.start(calls.append)
        thread.assert_called_once_with(target=calls.append, name='test-worker', daemon=True)
        thread.return_value.start.assert_called_once()

    @patch('application.helpers.queue_worker.time')
    def test_drain_without_a_running_worker(self, mock_time):
        """Nothing ever started: no waiting, whatever is queued."""
        QueueWorker(MagicMock(unfinished_tasks=1), 'test-worker', 30).drain()
        mock_time.sleep.assert_not_called()

    @patch('application.helpers.queue_worker.time')
    def test_drain_returns_when_empty(self, mock_time):
        """Nothing queued: no waiting at all."""
        mock_time.monotonic.return_value = 0
        self._started(0).drain()
        mock_time.sleep.assert_not_called()

    @patch('application.helpers.queue_worker.time')
    def test_drain_gives_up_at_the_deadline(self, mock_time):
        """A stuck queue doesn't block the exit forever."""
        mock_time.monotonic.side_effect = [0, 10, 40]
        self._started(1).drain()
        mock_time.sleep.assert_called_once()


class TestRecordExportError(unittest.TestCase):
    """Plugin.record_export_error"""

    @staticmethod
    def _plugin(debug):
        plugin = Plugin.__new__(Plugin)
        plugin.debug = debug
        plugin.log_details = []
        plugin.console = MagicMock()
        return plugin

    def test_noted_and_printed(self):
        """Without debug the loop goes on, the error is in the log entry."""
        plugin = self._plugin(False)
        plugin.record_export_error('srv01', ValueError('boom'))
        self.assertEqual(plugin.log_details, [('export_error srv01', 'boom')])
        plugin.console.assert_called_once_with(' Error in process: boom')

    def test_debug_raises(self):
        """With debug the same exception comes through."""
        plugin = self._plugin(True)
        error = ValueError('boom')
        with self.assertRaises(ValueError) as caught:
            plugin.record_export_error('srv01', error)
        self.assertIs(caught.exception, error)
        self.assertEqual(plugin.log_details, [])
