"""
Unit tests for checkmk downtimes module
"""
# pylint: disable=missing-function-docstring,protected-access,unused-argument
import datetime
import unittest
from unittest.mock import patch

from application.plugins.checkmk.cmk2 import CmkException
from application.plugins.checkmk.downtimes import CheckmkDowntimeSync
from tests import base_mock_init


class TestCheckMkDowntimeSync(unittest.TestCase):
    """Tests for CheckmkDowntimeSync"""

    def setUp(self):
        def mock_init(self_param, account=False):
            base_mock_init(self_param)

        self.init_patcher = patch(
            'application.plugins.checkmk.downtimes.CMK2.__init__', mock_init)
        self.init_patcher.start()
        self.sync = CheckmkDowntimeSync()

    def tearDown(self):
        self.init_patcher.stop()

    def test_ahead_days_no_offset(self):
        days = self.sync.ahead_days(None)
        self.assertEqual(len(days), 14)
        self.assertAlmostEqual(
            days[0].timestamp(),
            datetime.datetime.now().timestamp(),
            delta=2)

    def test_ahead_days_with_offset(self):
        days = self.sync.ahead_days(5)
        expected_start = datetime.datetime.now() + datetime.timedelta(days=5)
        self.assertEqual(len(days), 14)
        self.assertAlmostEqual(
            days[0].timestamp(),
            expected_start.timestamp(),
            delta=2)

    def test_calculate_downtime_days_every_day(self):
        days = self.sync.calculate_downtime_days('mon', 'day', None)
        self.assertEqual(len(days), 14)

    def test_calculate_downtime_days_workdays(self):
        days = self.sync.calculate_downtime_days('mon', 'workday', None)
        for day in days:
            self.assertNotIn(day.isoweekday(), [6, 7])

    def test_calculate_downtime_days_weekly(self):
        days = self.sync.calculate_downtime_days('mon', 'week', None)
        for day in days:
            self.assertEqual(day.weekday(), 0)  # Monday

    def test_calculate_downtime_days_unknown_returns_empty(self):
        days = self.sync.calculate_downtime_days('mon', 'unknown', None)
        self.assertEqual(days, [])

    def test_calculate_downtime_dates_yields_dates(self):
        dates = list(self.sync.calculate_downtime_dates('mon', '1.', False))
        self.assertTrue(len(dates) >= 1)
        for d in dates:
            self.assertEqual(d.strftime('%a').lower(), 'mon')

    def test_set_downtime_success(self):
        downtime = {
            'comment': 'test downtime',
            'start': datetime.datetime(2025, 1, 1, 10, 0, tzinfo=datetime.timezone.utc),
            'end': datetime.datetime(2025, 1, 1, 12, 0, tzinfo=datetime.timezone.utc),
            'duration': False,
        }

        with patch.object(self.sync, 'request') as mock_req, \
             patch('builtins.print'):
            mock_req.return_value = (None, {})
            self.sync.set_downtime('host1', downtime)

        mock_req.assert_called_once()
        call_data = mock_req.call_args[1]['data']
        self.assertEqual(call_data['host_name'], 'host1')
        self.assertNotIn('duration', call_data)
        self.assertEqual(self.sync.dt_stats['created'], 1)

    def test_set_downtime_with_duration(self):
        downtime = {
            'comment': 'test',
            'start': datetime.datetime(2025, 1, 1, 10, 0, tzinfo=datetime.timezone.utc),
            'end': datetime.datetime(2025, 1, 1, 12, 0, tzinfo=datetime.timezone.utc),
            'duration': 3600,
        }

        with patch.object(self.sync, 'request') as mock_req, \
             patch('builtins.print'):
            mock_req.return_value = (None, {})
            self.sync.set_downtime('host1', downtime)

        call_data = mock_req.call_args[1]['data']
        self.assertEqual(call_data['duration'], 3600)

    def test_set_downtime_exception_logged(self):
        downtime = {
            'comment': 'test',
            'start': datetime.datetime(2025, 1, 1, 10, 0, tzinfo=datetime.timezone.utc),
            'end': datetime.datetime(2025, 1, 1, 12, 0, tzinfo=datetime.timezone.utc),
            'duration': False,
        }

        with patch.object(self.sync, 'request', side_effect=CmkException("fail")), \
             patch('builtins.print'):
            self.sync.set_downtime('host1', downtime)

        self.assertEqual(self.sync.log_details[0][0], 'error')
        self.assertEqual(self.sync.dt_stats['failed'], 1)

    def test_do_hosts_downtimes_exception_logged(self):
        with patch.object(self.sync, 'calculate_configured_downtimes',
                          side_effect=Exception("boom")), \
             patch('builtins.print'):
            self.sync.do_hosts_downtimes('host1', {'rule': [{}]}, {'all': {}}, [])

        self.assertEqual(self.sync.log_details[0][0], 'error')

    def test_get_all_cmk_downtimes_groups_by_host_in_one_request(self):
        # Bulk read returns downtimes for several hosts in a single call;
        # they must come back grouped by hostname (this is what lets run()
        # replace the per-host reads that made the export hang).
        response = ({
            'value': [
                {'extensions': {'host_name': 'h1',
                                'start_time': '2025-01-01T10:00:00+00:00',
                                'end_time': '2025-01-01T12:00:00+00:00',
                                'comment': 'a', 'duration': 0}},
                {'extensions': {'host_name': 'h1',
                                'start_time': '2025-01-02T10:00:00+00:00',
                                'end_time': '2025-01-02T12:00:00+00:00',
                                'comment': 'b', 'duration': 0}},
                {'extensions': {'host_name': 'h2',
                                'start_time': '2025-01-03T10:00:00+00:00',
                                'end_time': '2025-01-03T12:00:00+00:00',
                                'comment': 'c', 'duration': 0}},
                {'extensions': {}},  # no host_name -> skipped, no crash
            ]
        }, {})

        with patch.object(self.sync, 'request', return_value=response) as mock_req:
            by_host = self.sync.get_all_cmk_downtimes()

        mock_req.assert_called_once()
        self.assertEqual(sorted(by_host), ['h1', 'h2'])
        self.assertEqual(len(by_host['h1']), 2)
        self.assertEqual(len(by_host['h2']), 1)
        self.assertIsInstance(by_host['h1'][0]['start'], datetime.datetime)

    def test_do_hosts_downtimes_uses_prefetched_and_skips_existing(self):
        existing = {
            'comment': 'exists',
            'start': datetime.datetime(2025, 1, 1, 10, 0, tzinfo=datetime.timezone.utc),
            'end': datetime.datetime(2025, 1, 1, 12, 0, tzinfo=datetime.timezone.utc),
            'duration': False,
        }
        fresh = dict(existing, comment='new',
                     start=datetime.datetime(2025, 2, 1, 10, 0, tzinfo=datetime.timezone.utc),
                     end=datetime.datetime(2025, 2, 1, 12, 0, tzinfo=datetime.timezone.utc))

        with patch.object(self.sync, 'calculate_configured_downtimes',
                          return_value=[existing, fresh]), \
             patch.object(self.sync, 'set_downtime') as mock_set, \
             patch('builtins.print'):
            # only the downtime that is not already present gets created
            self.sync.do_hosts_downtimes('h1', {'rule': [{}]}, {'all': {}},
                                         [existing])

        mock_set.assert_called_once_with('h1', fresh)
        # the skipped downtime is counted for the final status line
        self.assertEqual(self.sync.dt_stats['existing'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
