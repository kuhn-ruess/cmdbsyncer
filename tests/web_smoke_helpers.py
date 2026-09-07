"""
Harness for the tests that boot the *real* web application.

Every other test in this suite runs against the stubs installed by
``tests/__init__.py``, which occupy ``sys.modules['application']`` — so a
test that wants the real thing has to leave this process. These helpers run
a snippet of Python in a subprocess with the repository importable, an
in-memory ``mongomock`` backend and a generated ``local_config.py``, so no
MongoDB is needed and every run starts on an empty database.

The snippet is appended to ``PREAMBLE``, which boots the app, creates an
admin user and logs it in, and offers ``check()`` for asserting on a
response. A failing check exits non-zero with a readable message, which the
calling test surfaces.
"""

import os
import subprocess
import sys
import tempfile
import textwrap

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import mongomock  # noqa: F401  pylint: disable=unused-import
    HAVE_MONGOMOCK = True
except ImportError:
    HAVE_MONGOMOCK = False

SKIP_REASON = (
    "mongomock is not installed — run "
    "'pip install -r requirements-dev.txt' so the web application can be "
    "booted without a MongoDB"
)

# CRYPTOGRAPHY_KEY is a throwaway Fernet key for the subprocess only; the
# database it protects lives in memory and is gone when the run ends.
LOCAL_CONFIG = '''\
import mongomock

config = {
    'SECRET_KEY': 'web-smoke-test',
    'CRYPTOGRAPHY_KEY': b'8ZQ8Xh0mVQ7Y8t5s2r0nQ0m9K3jU1pP4wL6cB2aD7eE=',
    'CMDB_MODE': %(cmdb_mode)s,
    'REQUIRE_HTTPS': False,
    'MONGODB_SETTINGS': {
        'db': 'cmdb-api',
        'host': 'localhost',
        'port': 27017,
        'alias': 'default',
        'mongo_client_class': mongomock.MongoClient,
    },
}
'''

PREAMBLE = textwrap.dedent('''\
    import re
    import sys

    import application
    from application import app
    from application.models.user import User

    CMDB_MODE = app.config['CMDB_MODE']


    def fail(message):
        """End the run with a message the calling test can print."""
        sys.exit(f'[CMDB_MODE={CMDB_MODE}] {message}')


    def csrf(url):
        """The CSRF token of the form served at ``url``."""
        body = client.get(url).get_data(as_text=True)
        match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body)
        if not match:
            fail(f'no CSRF token in the form at {url}')
        return match.group(1)


    def check(url, expected, method='get', **kwargs):
        """Request ``url``; fail unless it answers ``expected``."""
        response = getattr(client, method)(url, **kwargs)
        if response.status_code != expected:
            fail(f'{method.upper()} {url} answered '
                 f'{response.status_code}, expected {expected}')
        return response


    user = User(email='smoke@example.com', name='Smoke user',
                global_admin=True)
    user.set_password('smoke-password')
    user.save()

    client = app.test_client()
''')


def run_against_app(snippet, cmdb_mode):
    """Run ``snippet`` against a freshly booted app. Returns the process."""
    with tempfile.TemporaryDirectory() as config_dir:
        for name, content in (
                ('local_config.py', LOCAL_CONFIG % {'cmdb_mode': cmdb_mode}),
                ('run.py', PREAMBLE + snippet),
        ):
            with open(os.path.join(config_dir, name), 'w',
                      encoding='utf-8') as handle:
                handle.write(content)

        env = dict(os.environ)
        env['CMDBSYNCER_CONFIG_DIR'] = config_dir
        env['PYTHONPATH'] = REPO_ROOT
        # Web mode is what these tests are about — the CLI path skips the
        # blueprints, the admin views and the login manager entirely.
        env.pop('CMDBSYNCER_CLI', None)

        return subprocess.run(
            [sys.executable, os.path.join(config_dir, 'run.py')],
            cwd=REPO_ROOT, env=env, capture_output=True,
            text=True, timeout=300, check=False,
        )
