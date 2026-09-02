"""
The CSRF token must outlive nothing but the session it belongs to.

Flask-WTF defaults to a one-hour token, counted from the moment the form
was rendered, while the admin session runs for ADMIN_SESSION_HOURS. A form
left open in between was rejected with "The CSRF token has expired" even
though the user was still logged in, and everything typed into it was
lost. The app therefore derives the limit from the session length.
"""
# pylint: disable=missing-function-docstring
import unittest

from tests.local_config_helpers import run_with_local_config

_PRINT_LIMIT = (
    "import application\n"
    "print('limit', application.app.config['WTF_CSRF_TIME_LIMIT'])\n"
)


class CsrfTimeLimitTest(unittest.TestCase):
    """application.app.config['WTF_CSRF_TIME_LIMIT']"""

    def _limit(self, local_config):
        result = run_with_local_config(local_config, _PRINT_LIMIT)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip().split('limit ')[-1]

    def test_default_matches_the_session_length(self):
        # BaseConfig ships ADMIN_SESSION_HOURS = 2 — two hours, not one.
        self.assertEqual(self._limit("config = {}\n"), '7200')

    def test_follows_admin_session_hours(self):
        self.assertEqual(
            self._limit("config = {'ADMIN_SESSION_HOURS': 6}\n"), '21600')

    def test_explicit_limit_wins(self):
        # A deployment that wants a short-lived token keeps that power.
        self.assertEqual(
            self._limit("config = {'WTF_CSRF_TIME_LIMIT': 60}\n"), '60')

    def test_zero_session_hours_falls_back(self):
        # 0/None is "unset" for the session helper too, which falls back
        # to eight hours — the token follows it instead of becoming 0,
        # which Flask-WTF would read as "never expires".
        self.assertEqual(
            self._limit("config = {'ADMIN_SESSION_HOURS': 0}\n"), '28800')


if __name__ == '__main__':
    unittest.main()
