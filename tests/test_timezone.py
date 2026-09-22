"""
Tests for the display timezone helper.

Timestamps are stored in UTC; the browser tells the server which clock
the reader uses via the `syncer_tz` cookie. The cookie is user input,
so the parsing is pinned here together with the fallbacks: an unknown
zone name has to fall through to the offset, and anything unusable has
to end up on UTC instead of raising in the middle of a page.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring

import datetime
import importlib.util
import os
import sys
import unittest
from zoneinfo import ZoneInfo

from flask import Flask


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Loaded straight from the file: the helper only needs Flask and the
# standard library, so it does not have to go through the stubbed
# `application` package.
_MODULE_PATH = os.path.join(
    REPO_ROOT, 'application', 'helpers', 'timezone.py'
)
_spec = importlib.util.spec_from_file_location('timezone_under_test', _MODULE_PATH)
timezone_helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(timezone_helper)

BERLIN = ZoneInfo('Europe/Berlin')


class CookieParsingTests(unittest.TestCase):
    def test_zone_name_wins(self):
        result = timezone_helper._timezone_from_cookie(  # pylint: disable=protected-access
            'Europe/Berlin|-120')
        self.assertEqual(result, BERLIN)

    def test_offset_only(self):
        result = timezone_helper._timezone_from_cookie('|-120')  # pylint: disable=protected-access
        self.assertEqual(result.utcoffset(None), datetime.timedelta(hours=2))

    def test_unknown_zone_falls_back_to_the_offset(self):
        # A server without a timezone database ends up here.
        result = timezone_helper._timezone_from_cookie(  # pylint: disable=protected-access
            'Mars/Olympus|60')
        self.assertEqual(result.utcoffset(None), datetime.timedelta(hours=-1))

    def test_junk_is_refused(self):
        for value in ('', None, 'x' * 200, '../../etc/passwd|x', '|9999',
                      'Mars/Olympus', '|x'):
            self.assertIsNone(
                timezone_helper._timezone_from_cookie(value))  # pylint: disable=protected-access

    def test_an_unusable_name_still_yields_the_offset(self):
        # Everything the name pattern rejects — shell characters, a path
        # — falls through to the offset rather than to an exception.
        result = timezone_helper._timezone_from_cookie(  # pylint: disable=protected-access
            'Europe/Berlin;rm -rf|-120')
        self.assertEqual(result.utcoffset(None), datetime.timedelta(hours=2))


class UserTimezoneTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_utc_without_a_request(self):
        self.assertEqual(timezone_helper.user_timezone(), timezone_helper.UTC)

    def test_utc_without_the_cookie(self):
        with self.app.test_request_context('/'):
            self.assertEqual(timezone_helper.user_timezone(), timezone_helper.UTC)

    def test_reads_the_cookie(self):
        with self.app.test_request_context(
                '/', headers={'Cookie': 'syncer_tz=Europe/Berlin|-120'}):
            self.assertEqual(timezone_helper.user_timezone(), BERLIN)

    def test_a_broken_cookie_does_not_raise(self):
        with self.app.test_request_context(
                '/', headers={'Cookie': 'syncer_tz=nonsense'}):
            self.assertEqual(timezone_helper.user_timezone(), timezone_helper.UTC)


class ConversionTests(unittest.TestCase):
    def test_naive_values_are_read_as_utc(self):
        stored = datetime.datetime(2026, 9, 22, 21, 30)
        local = timezone_helper.to_local(stored, BERLIN)
        self.assertEqual(local.hour, 23)
        self.assertEqual(local.date(), datetime.date(2026, 9, 22))

    def test_a_value_can_cross_the_date_line(self):
        stored = datetime.datetime(2026, 9, 22, 23, 30)
        self.assertEqual(timezone_helper.to_local(stored, BERLIN).date(),
                         datetime.date(2026, 9, 23))

    def test_winter_uses_the_winter_offset(self):
        stored = datetime.datetime(2026, 1, 15, 12, 0)
        self.assertEqual(timezone_helper.to_local(stored, BERLIN).hour, 13)

    def test_non_datetimes_pass_through(self):
        self.assertIsNone(timezone_helper.to_local(None))
        self.assertEqual(timezone_helper.to_local('N/A'), 'N/A')

    def test_format_local_outside_a_request_is_utc(self):
        stored = datetime.datetime(2026, 9, 22, 21, 30)
        self.assertEqual(timezone_helper.format_local(stored),
                         '2026-09-22 21:30:00')

    def test_format_local_of_nothing_is_empty(self):
        self.assertEqual(timezone_helper.format_local(None), '')


if __name__ == '__main__':
    unittest.main()
