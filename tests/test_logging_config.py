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
import unittest

from tests.local_config_helpers import run_with_local_config


# Stands in for the enterprise package: `load_package()` imports it by
# name, and it registers the same hook the real one does, so the OSS side
# of the wiring can be tested without the enterprise package installed.
_ENTERPRISE_STUB = """
from application.enterprise import register_feature


def _configure_logging(app, logger):
    import logging
    import sys
    print("CONFIGURE_LOGGING CALLED")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("RECORD: %(message)s"))
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    logger.handlers.clear()
    logger.propagate = True
    logger.setLevel(logging.INFO)
    return handler.stream


register_feature('json_logging')
register_feature('configure_logging', _configure_logging)
"""


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
        result = run_with_local_config(local_config, _EMIT + """
print(open('{workdir}/cmdbsyncer.log', encoding='utf-8').read())
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("INFO - Checkmk Host Export", result.stdout)
        self.assertIn("ERROR - Failed run", result.stdout)

    def test_log_level_shortcut(self):
        """LOG_LEVEL lifts both loggers without restating LOGGING."""
        result = run_with_local_config(
            "config = {'LOG_LEVEL': 'DEBUG'}\n",
            "import logging, application\n"
            "print(logging.getLogger('debug').level,"
            " logging.getLogger('syslog').level)\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "10 10")

    def test_broken_logging_config_does_not_block_startup(self):
        """A malformed LOGGING dict falls back instead of killing the app."""
        result = run_with_local_config(
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

    def test_command_runs_stay_plain_by_default(self):
        """A CLI run does not get the structured pipeline unasked."""
        result = run_with_local_config(
            "config = {}\n",
            "import logging, application\n"
            "print('root', logging.getLogger().level)\n",
            extra_files={'cmdbsyncer_enterprise/__init__.py':
                         _ENTERPRISE_STUB},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("CONFIGURE_LOGGING CALLED", result.stdout)
        # Third-party chatter stays out of the command's own output.
        self.assertIn("root 30", result.stdout)

    def test_json_logging_cli_opts_command_runs_in(self):
        """JSON_LOGGING_CLI hands CLI runs to the structured pipeline."""
        result = run_with_local_config(
            "config = {'JSON_LOGGING_CLI': True}\n",
            "import logging, application\n"
            "print('root', logging.getLogger().level)\n",
            extra_files={'cmdbsyncer_enterprise/__init__.py':
                         _ENTERPRISE_STUB},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CONFIGURE_LOGGING CALLED", result.stdout)
        # Still no third-party chatter — only the syncer's own loggers,
        # which propagate regardless of the root level, reach the handler.
        # The print itself now arrives as a record rather than raw text.
        self.assertIn("RECORD: root 30", result.stdout)

    def test_terminal_run_stays_readable(self):
        """A person at a terminal gets plain text, never the JSON.

        JSON_LOGGING_CLI is meant for cron runs and pipes feeding a
        collector. On a terminal the same stream is unreadable — one
        record carries a whole stack trace on a single line.
        """
        result = run_with_local_config(
            "config = {'JSON_LOGGING_CLI': True}\n",
            "import sys\n"
            "class _Tty:\n"
            "    def __getattr__(self, name):\n"
            "        return getattr(sys.__stdout__, name)\n"
            "    def isatty(self):\n"
            "        return True\n"
            "sys.stdout = _Tty()\n"
            "import application\n",
            extra_files={'cmdbsyncer_enterprise/__init__.py':
                         _ENTERPRISE_STUB},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("CONFIGURE_LOGGING CALLED", result.stdout)

    def test_file_target_survives_a_terminal_run(self):
        """A file target is not the terminal, so the run keeps both.

        The readability rule exists because JSON on a terminal is
        unreadable. Records going to a log file are not on the terminal
        at all, so they are produced there as well — and the plain
        output the person is watching stays plain.
        """
        result = run_with_local_config(
            "config = {'JSON_LOGGING_CLI': True,\n"
            "          'JSON_LOGGING_FILE': '{workdir}/syncer.jsonl'}\n",
            "import sys\n"
            "class _Tty:\n"
            "    def __getattr__(self, name):\n"
            "        return getattr(sys.__stdout__, name)\n"
            "    def isatty(self):\n"
            "        return True\n"
            "sys.stdout = _Tty()\n"
            "import application\n"
            "print('Try 1 of 2 failed')\n",
            extra_files={'cmdbsyncer_enterprise/__init__.py':
                         _ENTERPRISE_STUB},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CONFIGURE_LOGGING CALLED", result.stdout)
        # The person's own output is theirs to read, not a record.
        self.assertIn("Try 1 of 2 failed", result.stdout)
        self.assertNotIn("RECORD: Try 1 of 2 failed", result.stdout)

    def test_printed_progress_becomes_a_record(self):
        """What a command prints reaches the collector as a record.

        The progress of a run is written with `print()` in hundreds of
        places. Left alone it lands between the records unformatted,
        and the retries and errors it carries never reach the pipeline.
        """
        result = run_with_local_config(
            "config = {'JSON_LOGGING_CLI': True}\n",
            "import application\n"
            "print('\\033[94mTry 1 of 2 failed\\033[0m')\n"
            "print('-------------------')\n",
            extra_files={'cmdbsyncer_enterprise/__init__.py':
                         _ENTERPRISE_STUB},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # Formatted by the handler, with the colour escapes stripped.
        self.assertIn("RECORD: Try 1 of 2 failed", result.stdout)
        # A rule of dashes is not an event.
        self.assertNotIn("-------------------", result.stdout)

    def test_shell_completion_run_gets_no_structured_pipeline(self):
        """Completion parses stdout, so nothing may be written to it.

        Click builds the completion script by running the CLI and
        reading its stdout. A marker line from the structured pipeline
        landed inside that script, and the shell sourcing it then tried
        to run the JSON as a command.
        """
        result = run_with_local_config(
            "config = {'JSON_LOGGING_CLI': True}\n",
            "import os\n"
            "os.environ['_CMDBSYNCER_COMPLETE'] = 'bash_source'\n"
            "import application\n",
            extra_files={'cmdbsyncer_enterprise/__init__.py':
                         _ENTERPRISE_STUB},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("CONFIGURE_LOGGING CALLED", result.stdout)

    def test_structured_record_matches_the_web_log(self):
        """Every detail row and the traceback reach the structured record.

        `event_details` is a dict, so a key that occurs more than once —
        an export appends one ('error', …) per failed host — used to
        overwrite itself down to the last one while the Log view kept
        them all.
        """
        snippet = """
import logging
from unittest.mock import patch
import application
import application.modules.log.log as logmod


class _Capture(logging.Handler):
    seen = []

    def emit(self, record):
        _Capture.seen.append(record)


syslog = logging.getLogger('syslog')
syslog.handlers = [_Capture()]
syslog.setLevel(logging.INFO)

with patch.object(logmod, 'LogEntry'), patch.object(logmod, 'DetailEntry'):
    try:
        raise RuntimeError('connection reset')
    except RuntimeError:
        logmod.Log().log('Export', source='cmk_export', details=[
            ('num_created', '3'),
            ('error', 'host-a'),
            ('error', 'host-b'),
        ])

record = _Capture.seen[-1]
print(record.event_details)
print('TRACEBACK', 'RuntimeError' in getattr(record, 'event_traceback', ''))
"""
        result = run_with_local_config("config = {}\n", snippet)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("'num_created': '3'", result.stdout)
        self.assertIn("'error': ['host-a', 'host-b']", result.stdout)
        self.assertIn("TRACEBACK True", result.stdout)

    def test_default_syslog_handler_address_is_sendable(self):
        """The shipped SysLogHandler address must be a tuple, not a list."""
        from application.config import BaseConfig  # pylint: disable=import-outside-toplevel
        address = BaseConfig.LOGGING['handlers']['syslog']['address']
        # socket.sendto() raises TypeError on a list address, which turns
        # every single log entry into a handler traceback on stderr.
        self.assertIsInstance(address, tuple)


if __name__ == "__main__":
    unittest.main()
