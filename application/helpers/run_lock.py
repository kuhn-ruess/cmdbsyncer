"""
One run per export and account at a time

Two runs of the same export against the same account, like a cron group and
a run started by hand, both compare with the target before either of them
writes. Both then create the same objects, and the next run has to remove
the duplicates again. ``exclusive_per_account`` lets the second run stop
with a message instead.

A lock whose process is gone (crash, kill -9, container restart) is taken
over, the same way cron clears its own stale locks.
"""
import inspect
import os
import socket
from datetime import datetime
from functools import wraps

from mongoengine.errors import NotUniqueError

from application.helpers.task_status import task_failed
from application.models.cron import RunLock
from application.modules.debug import ColorCodes as CC


class RunLockedError(Exception):
    """The export already runs for this account."""


def pid_alive(pid):
    """
    Signal 0 does not send a signal but performs the existence / permission
    check. Anything raising means the process is gone.
    """
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def process_start(pid):
    """
    Local start time of the process ``pid``, from /proc. None where /proc
    is missing (not Linux) or the process is gone.
    """
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="ascii") as handle:
            # The name in brackets may hold spaces, the fields after it don't
            ticks = int(handle.read().rsplit(")", 1)[1].split()[19])
        with open("/proc/stat", encoding="ascii") as handle:
            boot = next(int(line.split()[1]) for line in handle
                        if line.startswith("btime "))
        return datetime.fromtimestamp(boot + ticks / os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def _stale(lock):
    """
    Whether the holder of ``lock`` is gone. Like cron, this takes the runs
    to be local: a recreated container has a new hostname and counts its
    PIDs from 1 again, so the hostname only goes into the message.
    """
    if not pid_alive(lock.pid):
        return True
    started = process_start(lock.pid)
    # A PID that now belongs to a process started after the lock.
    return started is not None and lock.started is not None \
        and started > lock.started


def acquire(name):
    """
    Take the lock ``name``. Returns None when it is ours now, otherwise the
    lock document of the run holding it.
    """
    mine = {'pid': os.getpid(), 'hostname': socket.gethostname(),
            'started': datetime.now()}
    try:
        RunLock(name=name, **mine).save(force_insert=True)
        return None
    except NotUniqueError:
        pass
    current = RunLock.objects(name=name).first()
    if current is None:
        # Released between our insert and the lookup.
        return acquire(name)
    if not _stale(current):
        return current
    # Atomic: of two runs taking over the same stale lock only one wins.
    taken = RunLock.objects(name=name, pid=current.pid,
                            started=current.started).modify(
        set__pid=mine['pid'], set__hostname=mine['hostname'],
        set__started=mine['started'])
    return None if taken else RunLock.objects(name=name).first()


def release(name):
    """Give the lock ``name`` back, when this process holds it."""
    RunLock.objects(name=name, pid=os.getpid(),
                    hostname=socket.gethostname()).delete()


def exclusive_per_account(job_name):
    """
    Decorator for an export taking the account as first argument (or as
    ``account=``): a second run for the same account stops with a message
    and is reported to cron as failed. A dry run writes nothing and is
    never blocked.
    """
    def decorator(func):
        signature = inspect.signature(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            given = signature.bind_partial(*args, **kwargs).arguments
            if given.get('dry_run'):
                return func(*args, **kwargs)
            account = given.get('account')
            name = f"{job_name}:{account}"
            holder = acquire(name)
            if holder is not None:
                since = holder.started.strftime('%Y-%m-%d %H:%M:%S') \
                    if holder.started else 'an unknown time'
                error = RunLockedError(
                    f"{job_name} for {account} already runs since {since} "
                    f"(PID {holder.pid} on {holder.hostname}), this run "
                    "is skipped")
                print(f"{CC.FAIL}{error}{CC.ENDC}")
                task_failed(error)
                return None
            try:
                return func(*args, **kwargs)
            finally:
                release(name)
        return wrapper
    return decorator
