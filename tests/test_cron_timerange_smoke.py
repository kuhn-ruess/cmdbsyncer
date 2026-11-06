"""
The time window of a cron group, also one that runs over midnight.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import datetime as real_datetime
from types import SimpleNamespace
from unittest.mock import patch

from application.plugins import cron


def at(hour):
    """A datetime class whose now() is today at the given hour."""
    class Fixed(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 6, hour, 30)
    return Fixed


def job(t_from, t_to):
    return SimpleNamespace(timerange_from=str(t_from), timerange_to=str(t_to),
                           interval='hour', custom_interval_in_minutes=None)


def in_window(hour, t_from, t_to):
    with patch.object(cron, 'datetime', at(hour)):
        return cron.in_timerange(job(t_from, t_to))


def next_run(hour, t_from, t_to, last_start=None):
    with patch.object(cron, 'datetime', at(hour)):
        result = cron.calc_next_run(job(t_from, t_to), last_start)
    return result.day, result.hour, result.minute


for hour, expected in ((8, True), (18, False), (7, False)):
    eq(in_window(hour, 8, 18), expected, f'8 to 18 at {hour}')
eq(in_window(23, 0, 24), True, 'whole day')
for hour in (22, 23, 0, 3):
    eq(in_window(hour, 22, 4), True, f'22 to 4 at {hour}')
for hour in (4, 12, 21):
    eq(in_window(hour, 22, 4), False, f'22 to 4 at {hour}')

last = real_datetime.datetime(2026, 11, 6, 23, 0)
eq(next_run(23, 22, 4, last), (7, 0, 0), 'next run inside a window over midnight')
eq(next_run(4, 22, 4), (6, 22, 0), 'a window over midnight starts again tonight')
eq(next_run(19, 8, 18), (7, 8, 0), 'a window within a day starts again tomorrow')

print('CRON_WINDOW_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CronTimerangeTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_time_windows(self):
        """Windows within a day stay as they are, over midnight they work."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('CRON_WINDOW_OK', result.stdout)
