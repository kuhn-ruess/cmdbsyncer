"""
Lets a job tell cron that it failed

The wrappers around a job catch its errors, so the command line shows a
message instead of a traceback. Cron can't see those errors by itself and
would count the task as a success.
"""
_FAILURE = {}


def task_failed(error):
    """Remember that the running job failed, for ``take_task_failure``."""
    _FAILURE['error'] = error


def take_task_failure():
    """The error of the job since the last call, None if it went fine."""
    return _FAILURE.pop('error', None)
