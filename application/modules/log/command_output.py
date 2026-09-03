"""
Route what a command prints into the log pipeline.

The progress of a run — the retries, the timeouts, the per-host results
— is written with `print()` in about 550 places across the plugins.
That is the right call for someone watching a terminal, but on a run
feeding a log collector those lines carry exactly the detail the
collector is after, and they would bypass the pipeline entirely.

Rewriting every call site is not the way to get there. Standing in for
`sys.stdout` for the duration of such a run is: every line printed
becomes one record, in whatever shape the configured handler writes.
"""
import logging
import re

# Colour and cursor escapes from ColorCodes. Meaningful on a terminal,
# noise inside a log record.
_ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

# Plugins print rules of dashes to separate sections of a run. As a
# record such a line carries nothing.
_SEPARATOR = re.compile(r'^[-=_*\s]*$')


class CommandOutputToLog:
    """A write-only text stream that logs whole lines.

    Deliberately not a `TextIOBase`: only the handful of attributes a
    `print()` and a well-behaved caller touch are implemented, and
    `isatty()` answers False so nothing downstream starts colouring for
    a terminal that is not there.
    """

    def __init__(self, logger=None, level=logging.INFO):
        self._logger = logger or logging.getLogger('debug')
        self._level = level
        self._buffer = ''

    def write(self, text):
        """Buffer until a line is complete, then log it."""
        self._buffer += text
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            self._log(line)
        return len(text)

    def writelines(self, lines):
        """Part of the stream protocol; some callers use it."""
        for line in lines:
            self.write(line)

    def _log(self, line):
        line = _ANSI.sub('', line).rstrip()
        if _SEPARATOR.match(line):
            return
        self._logger.log(self._level, line,
                         extra={'event_source': 'command_output'})

    def flush(self):
        """Log a trailing line that never got its newline."""
        if self._buffer:
            line, self._buffer = self._buffer, ''
            self._log(line)

    def isatty(self):
        """Never a terminal — this stream is going to a log collector."""
        return False

    def writable(self):
        """Stream protocol."""
        return True
