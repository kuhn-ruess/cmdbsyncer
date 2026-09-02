"""
Regression tests for the logging pipeline wiring.

The `LOGGING` dict in `local_config.py` used to be ignored completely:
`dictConfig()` ran before the deployment config was merged, so a
customer-configured syslog target or log file never received a single
record. On top of that the shipped `syslog` logger had no writer at all
and its handler address was a list, which `socket.sendto()` rejects.

These tests run the real `application` package in a subprocess — the
package-level test bootstrap stubs `application` out in `sys.modules`,
and here we specifically need the genuine import-time ordering.
"""
import os
import subprocess
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_with_local_config(local_config, snippet):
    """
    Write `local_config` into a scratch directory, import `application`
    from there and run `snippet`. `{workdir}` is substituted with the
    scratch path in both. Returns the CompletedProcess.

    The scratch directory is also the working directory: the repo root
    usually carries its own `local_config.py`, and cwd wins on sys.path.
    """
    with tempfile.TemporaryDirectory() as workdir:
        with open(os.path.join(workdir, "local_config.py"), "w",
                  encoding="utf-8") as config_file:
            config_file.write(local_config.replace("{workdir}", workdir))
        env = dict(os.environ)
        env["PYTHONPATH"] = _REPO_ROOT
        # CLI mode keeps the import light — no blueprints, no Flask-Admin
        # scaffolding, and therefore no live MongoDB needed.
        env["CMDBSYNCER_CLI"] = "1"
        env["CMDBSYNCER_CONFIG_DIR"] = workdir
        return subprocess.run(
            [sys.executable, "-c", snippet.replace("{workdir}", workdir)],
            cwd=workdir, env=env, capture_output=True, text=True, check=False,
        )


# Emits one entry through the central Log() module with the MongoEngine
# documents patched out, which is exactly the path every import/export
# takes at the end of a run.
_EMIT = """
from unittest.mock import patch
import application
import application.modules.log.log as logmod
with patch.object(logmod, 'LogEntry'), patch.object(logmod, 'DetailEntry'):
    logmod.Log().log('Checkmk Host Export', source='TEST',
                     details=[('created', '3')])
    logmod.Log().log('Failed run', source='TEST', details=[('error', 'boom')])
"""


class TestLoggingConfig(unittest.TestCase):
    """Deployment-configured logging really receives the log entries."""

    def test_local_config_logging_is_applied(self):
        """A LOGGING override in local_config.py wins over BaseConfig."""
        local_config = """
config = {
    'LOGGING': {
        'version': 1,
        'formatters': {'syslog': {'format': '%(levelname)s - %(message)s'}},
        'handlers': {
            'syslog': {'class': 'logging.FileHandler',
                       'filename': '{workdir}/cmdbsyncer.log',
                       'formatter': 'syslog'},
        },
        'loggers': {
            'syslog': {'handlers': ['syslog'], 'level': 'INFO',
                       'propagate': False},
        },
    },
}
"""

        # The scratch directory is gone once the helper returns, so the
        # snippet reads the file back itself.
        result = _run_with_local_config(local_config, _EMIT + """
print(open('{workdir}/cmdbsyncer.log', encoding='utf-8').read())
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("INFO - Checkmk Host Export", result.stdout)
        self.assertIn("ERROR - Failed run", result.stdout)

    def test_log_level_shortcut(self):
        """LOG_LEVEL lifts both loggers without restating LOGGING."""
        result = _run_with_local_config(
            "config = {'LOG_LEVEL': 'DEBUG'}\n",
            "import logging, application\n"
            "print(logging.getLogger('debug').level,"
            " logging.getLogger('syslog').level)\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "10 10")

    def test_broken_logging_config_does_not_block_startup(self):
        """A malformed LOGGING dict falls back instead of killing the app."""
        result = _run_with_local_config(
            "config = {'LOGGING': {'version': 1,\n"
            "    'handlers': {'x': {'class': 'nope.NoSuchHandler'}},\n"
            "    'loggers': {'debug': {'handlers': ['x']}}}}\n",
            "import logging, application\n"
            "print([type(h).__name__ for h in"
            " logging.getLogger('syslog').handlers])\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("falling back to the built-in defaults", result.stderr)
        self.assertIn("SysLogHandler", result.stdout)

    def test_default_syslog_handler_address_is_sendable(self):
        """The shipped SysLogHandler address must be a tuple, not a list."""
        from application.config import BaseConfig  # pylint: disable=import-outside-toplevel
        address = BaseConfig.LOGGING['handlers']['syslog']['address']
        # socket.sendto() raises TypeError on a list address, which turns
        # every single log entry into a handler traceback on stderr.
        self.assertIsInstance(address, tuple)


if __name__ == "__main__":
    unittest.main()
