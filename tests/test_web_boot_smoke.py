"""
Smoke test: the web application actually boots.

Every other test in this suite runs against the stubs installed by
``tests/__init__.py`` — no test builds the real Flask app, so a change that
makes ``application`` unimportable, or that breaks one of the ~80 admin
views while they are being registered, passes the whole suite and only
fails when gunicorn starts. That is how 4.3.0 shipped a web interface that
could not boot at all with the default configuration.

This test closes that gap. It runs the real import in a **subprocess** (the
stubs in ``tests/__init__.py`` occupy ``sys.modules['application']`` in this
one) against an in-memory ``mongomock`` backend, so it needs no MongoDB, and
asserts that the login page answers. Both values of ``CMDB_MODE`` are
covered — the flag changes how the host and object views are built, and the
default is off.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import mongomock  # noqa: F401  pylint: disable=unused-import
    HAVE_MONGOMOCK = True
except ImportError:
    HAVE_MONGOMOCK = False


LOCAL_CONFIG = '''\
import mongomock

config = {
    'SECRET_KEY': 'web-boot-smoke-test',
    'CRYPTOGRAPHY_KEY': b'8ZQ8Xh0mVQ7Y8t5s2r0nQ0m9K3jU1pP4wL6cB2aD7eE=',
    'CMDB_MODE': %(cmdb_mode)s,
    'MONGODB_SETTINGS': {
        'db': 'cmdb-api',
        'host': 'localhost',
        'port': 27017,
        'alias': 'default',
        'mongo_client_class': mongomock.MongoClient,
    },
}
'''

BOOT_SCRIPT = textwrap.dedent('''\
    import sys

    import application
    from application import app

    admin = app.extensions['admin'][0]
    if not admin._views:  # pylint: disable=protected-access
        sys.exit('no admin views were registered')

    response = app.test_client().get('/login')
    if response.status_code != 200:
        sys.exit(f'GET /login answered {response.status_code}')

    print('BOOT_OK', len(admin._views))  # pylint: disable=protected-access
''')


@unittest.skipUnless(
    HAVE_MONGOMOCK,
    "mongomock is not installed — install requirements-dev.txt so this "
    "test can boot the app without a MongoDB",
)
class TestWebBootSmoke(unittest.TestCase):
    """The app must import and serve its login page."""

    def _boot(self, cmdb_mode):
        """Boot the app in a subprocess and return its stdout."""
        with tempfile.TemporaryDirectory() as config_dir:
            config_file = os.path.join(config_dir, 'local_config.py')
            with open(config_file, 'w', encoding='utf-8') as handle:
                handle.write(LOCAL_CONFIG % {'cmdb_mode': cmdb_mode})
            boot_file = os.path.join(config_dir, 'boot.py')
            with open(boot_file, 'w', encoding='utf-8') as handle:
                handle.write(BOOT_SCRIPT)

            env = dict(os.environ)
            env['CMDBSYNCER_CONFIG_DIR'] = config_dir
            env['PYTHONPATH'] = REPO_ROOT
            # Web mode is what we are testing — the CLI path skips the
            # blueprints, the admin views and the login manager entirely.
            env.pop('CMDBSYNCER_CLI', None)

            return subprocess.run(
                [sys.executable, boot_file],
                cwd=REPO_ROOT, env=env, capture_output=True,
                text=True, timeout=300, check=False,
            )

    def test_boots_without_cmdb_mode(self):
        """The default configuration — CMDB_MODE off."""
        result = self._boot('False')
        self.assertEqual(
            result.returncode, 0,
            f"the web app does not start with CMDB_MODE off:\n"
            f"{result.stdout}\n{result.stderr}")
        self.assertIn('BOOT_OK', result.stdout)

    def test_boots_with_cmdb_mode(self):
        """The CMDB variant builds the host and object views differently."""
        result = self._boot('True')
        self.assertEqual(
            result.returncode, 0,
            f"the web app does not start with CMDB_MODE on:\n"
            f"{result.stdout}\n{result.stderr}")
        self.assertIn('BOOT_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
