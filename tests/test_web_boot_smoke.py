"""
Smoke test: the web application actually boots.

Every other test in this suite runs against the stubs installed by
``tests/__init__.py`` — no test builds the real Flask app, so a change that
makes ``application`` unimportable, or that breaks one of the ~80 admin
views while they are being registered, passes the whole suite and only
fails when gunicorn starts. That is how 4.3.0 shipped a web interface that
could not boot at all with the default configuration.

Both values of ``CMDB_MODE`` are covered — the flag changes how the host and
object views are built, and the default is off. What the app does once it
runs is covered by ``tests/test_web_requests_smoke.py``.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


BOOT = '''
admin = app.extensions['admin'][0]
if not admin._views:
    fail('no admin views were registered')

check('/login', 200)
print('BOOT_OK', len(admin._views))
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestWebBootSmoke(unittest.TestCase):
    """The app must import and serve its login page."""

    def _assert_boots(self, cmdb_mode):
        """Boot with `cmdb_mode` and fail loudly if it does not come up."""
        result = run_against_app(BOOT, cmdb_mode)
        self.assertEqual(
            result.returncode, 0,
            f"the web app does not start with CMDB_MODE={cmdb_mode}:\n"
            f"{result.stdout}\n{result.stderr}")
        self.assertIn('BOOT_OK', result.stdout)

    def test_boots_without_cmdb_mode(self):
        """The default configuration — CMDB_MODE off."""
        self._assert_boots('False')

    def test_boots_with_cmdb_mode(self):
        """The CMDB variant builds the host and object views differently."""
        self._assert_boots('True')


if __name__ == '__main__':
    unittest.main()
