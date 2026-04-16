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

    def test_get_current_cmk_downtimes(self):
        response = ({
            'value': [
                {
                    'extensions': {
                        'start_time': '2025-01-01T10:00:00+00:00',
                        'end_time': '2025-01-01T12:00:00+00:00',
                        'comment': 'test',
                        'duration': 0,
                    }
                }
            ]
        }, {})

        with patch.object(self.sync, 'request', return_value=response):
            downtimes = list(self.sync.get_current_cmk_downtimes('host1'))

        self.assertEqual(len(downtimes), 1)
        self.assertEqual(downtimes[0]['comment'], 'test')

    def test_do_hosts_downtimes_exception_logged(self):
        with patch.object(self.sync, 'calculate_configured_downtimes',
                          side_effect=Exception("boom")), \
             patch('builtins.print'):
            self.sync.do_hosts_downtimes('host1', {'rule': [{}]}, {'all': {}})

        self.assertEqual(self.sync.log_details[0][0], 'error')


if __name__ == '__main__':
    unittest.main(verbosity=2)
