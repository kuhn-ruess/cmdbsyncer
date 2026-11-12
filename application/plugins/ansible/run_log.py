"""
Entries of the Ansible runs in the log of the Syncer (Settings, Log, source
Ansible): what a run does when it starts, and how it ended, with the result
per host and what failed where.

The output of ansible-playbook is read as it is printed: the TASK headers,
the fatal lines of failed hosts, ERROR! lines of Ansible itself and the
PLAY RECAP. Extra vars and passwords never go into an entry.
"""
import json
import re

from application import log

LOG_SOURCE = 'Ansible'
# Failures listed per entry; the run page has the whole log
MAX_FAILURES = 20
MAX_MESSAGE = 300

_TASK = re.compile(r'^TASK \[(.*)\]')
_FATAL = re.compile(r'^fatal: \[([^\]]+)\]: (FAILED|UNREACHABLE)! => (.*)$')
_MSG = re.compile(r'"msg": "((?:[^"\\]|\\.)*)"')
_RECAP = re.compile(r'^(\S+)\s+: (ok=\d+.*)$')
_FAILED = re.compile(r'\b(?:failed|unreachable)=([1-9]\d*)')
_ERROR = re.compile(r'^(?:ERROR!|\[ERROR\]:?)\s*(.*)$')
# Printed before the fatal line of a module that crashed, whose own message
# is only "MODULE FAILURE"
_EXCEPTION = re.compile(r'An exception occurred during task execution\..*The error was: (.*)$')


def _short(text):
    text = ' '.join(str(text).split())
    return text if len(text) <= MAX_MESSAGE else text[:MAX_MESSAGE] + '...'


def _unquote(text):
    """A JSON string body as text, the raw body when it does not parse"""
    try:
        return json.loads(f'"{text}"')
    except ValueError:
        return text


def summarize(output):
    """
    ``{'recap': {host: counts}, 'failures': [(host, task, kind, message)],
    'errors': [line]}`` from the output of ansible-playbook.
    """
    recap, failures, errors = {}, [], []
    task = exception = ''
    in_recap = False
    for line in (output or '').splitlines():
        line = line.rstrip()
        if match := _TASK.match(line):
            task, exception = match.group(1), ''
        elif match := _EXCEPTION.search(line):
            exception = match.group(1)
        elif match := _FATAL.match(line):
            host, kind, rest = match.groups()
            message = _MSG.search(rest)
            message = _unquote(message.group(1)) if message else rest
            if exception and message.startswith('MODULE FAILURE'):
                message = exception
            failures.append((host, task, kind.lower(), _short(message)))
        elif match := _ERROR.match(line):
            errors.append(_short(match.group(1) or line))
        elif line.startswith('PLAY RECAP'):
            in_recap = True
        elif in_recap and (match := _RECAP.match(line)):
            recap[match.group(1)] = ' '.join(match.group(2).split())
    return {'recap': recap, 'failures': failures, 'errors': errors}


def failed_hosts(summary):
    """The hosts the recap counts as failed or unreachable"""
    return sorted(host for host, counts in summary['recap'].items()
                  if _FAILED.search(counts))


def _base(stats):
    return [('playbook', stats.playbook),
            ('hosts', stats.target_host or 'all hosts of the inventory'),
            ('mode', 'preview' if stats.mode == 'check' else 'run'),
            ('source', stats.source or ''),
            ('triggered_by', stats.triggered_by or ''),
            ('run', str(stats.pk))]


def log_start(stats, provider):
    """The entry of a starting run; skipped for playbook rules, which fire often"""
    if stats.source == 'rule':
        return
    try:
        log.log(f"Ansible: {stats.playbook} started", source=LOG_SOURCE,
                details=_base(stats) + [('inventory', provider or '')])
    except Exception:  # pylint: disable=broad-exception-caught
        # A log that can't be written must not stop the run
        pass


def log_end(stats, hint=''):
    """The entry of an ended run with its result and what failed"""
    try:
        summary = summarize(stats.log)
        details = _base(stats) + [('status', stats.status),
                                  ('exit_code', stats.exit_code)]
        if stats.started_at and stats.ended_at:
            duration = str(stats.ended_at - stats.started_at)
            details.append(('duration', duration.split('.', maxsplit=1)[0]))
        details += [('host', f"{host}: {counts}")
                    for host, counts in sorted(summary['recap'].items())]
        if stats.status == 'failure':
            problems = [f"{host}: {task}: {message}" if task else f"{host}: {message}"
                        for host, task, _kind, message in summary['failures']]
            problems += summary['errors']
            if not problems:
                # Nothing Ansible named: the last lines say what happened
                problems = [_short(' | '.join((stats.log or '').strip().splitlines()[-3:]))
                            or f"ansible-playbook exited with {stats.exit_code}"]
            details += [('error', problem) for problem in problems[:MAX_FAILURES]]
            if len(problems) > MAX_FAILURES:
                details.append(('error', f"and {len(problems) - MAX_FAILURES} more, "
                                         "see the run"))
            if hint.strip():
                details.append(('hint', _short(hint)))
            if hosts := failed_hosts(summary):
                details.append(('affected_hosts', hosts))
        log.log(f"Ansible: {stats.playbook} {stats.status}", source=LOG_SOURCE,
                details=details)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
