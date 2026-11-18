"""
The crontab entry that starts `cmdbsyncer cron run_jobs`, and whether it runs
"""
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
from datetime import timedelta

# Comment above the entry, so a later look at the crontab says what it is
MARKER = '# CMDBsyncer: runs the due cron groups'


class CrontabError(Exception):
    """The crontab could not be read or written, the message says why"""


def config_dir():
    """
    Directory of the local_config.py this process uses, None without one.

    The cron job changes into it, so it finds the same configuration and
    the same plugins directory as the command that installed it.
    """
    spec = importlib.util.find_spec('local_config')
    if not spec or not spec.origin:
        return None
    return os.path.dirname(os.path.abspath(spec.origin))


def syncer_binary():
    """The cmdbsyncer command this process was started with"""
    started = sys.argv[0] if sys.argv else ''
    if os.path.basename(started) == 'cmdbsyncer':
        return os.path.abspath(started)
    return os.path.join(os.path.dirname(sys.executable), 'cmdbsyncer')


def cron_line(interval, directory, binary, python=None):
    """
    The crontab line. It names the interpreter of this process: the PATH
    of cron would otherwise pick a python without the Syncer's packages
    for a checkout's ./cmdbsyncer. stdout goes away, the Syncer logs every
    pass itself; stderr stays, so a crash still reaches the mail or syslog
    of cron.
    """
    python = python or sys.executable
    return (f"*/{interval} * * * * cd {shlex.quote(directory)} && "
            f"{shlex.quote(python)} {shlex.quote(binary)} cron run_jobs > /dev/null")


def existing_entry(crontab):
    """The active line that already runs `cron run_jobs`, or None"""
    for line in crontab.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and 'cron run_jobs' in stripped:
            return stripped
    return None


def with_entry(crontab, line):
    """The crontab with the entry appended, everything else kept"""
    text = crontab if not crontab or crontab.endswith('\n') else crontab + '\n'
    return f"{text}{MARKER}\n{line}\n"


def _crontab_command():
    binary = shutil.which('crontab')
    if not binary:
        raise CrontabError("The crontab command is missing, install cron first")
    return binary


def read_crontab():
    """The crontab of the current user, empty when there is none yet"""
    result = subprocess.run([_crontab_command(), '-l'], capture_output=True,
                            text=True, check=False)
    if result.returncode == 0:
        return result.stdout
    if 'no crontab' in result.stderr.lower():
        return ''
    raise CrontabError(f"Reading the crontab failed: {result.stderr.strip()}")


def write_crontab(crontab):
    """Replace the crontab of the current user"""
    result = subprocess.run([_crontab_command(), '-'], input=crontab,
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise CrontabError(f"Writing the crontab failed: {result.stderr.strip()}")


# Without a pass of run_jobs for longer than this, the cron job is taken
# as not running. Above the longest interval `cron install` accepts.
HEARTBEAT_LIMIT = timedelta(hours=1)


def missing_heartbeat(last_pass, now):
    """Whether run_jobs has not run within HEARTBEAT_LIMIT, or never"""
    return not last_pass or now - last_pass > HEARTBEAT_LIMIT
