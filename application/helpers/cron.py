"""
Cron Job Managment Helper
"""
import os
import sys
from application import cron_register, plugin_register

# Resolved once per filename seen
_filename_to_plugin = {}

# Resolved on first register_cronjob call
_is_disabled = None  # pylint: disable=invalid-name


def _plugin_dirname_for_file(filename):
    """Map a source filename to its plugin directory name (cached)."""
    cached = _filename_to_plugin.get(filename)
    if cached is not None:
        return cached  # "" means "not inside a plugin"
    parts = filename.split(os.sep)
    for i, part in enumerate(parts):
        if part == 'plugins' and i + 1 < len(parts):
            candidate = parts[i + 1]
            if not candidate.endswith('.py'):
                _filename_to_plugin[filename] = candidate
                return candidate
    _filename_to_plugin[filename] = ""
    return ""


def register_cronjob(job_name, job_function):
    """
    Register Cronjob to the System

    Pass the Unqiue Name and the Function reference.
    """
    global _is_disabled  # pylint: disable=global-statement
    if _is_disabled is None:
        from application.helpers.plugins import is_plugin_disabled  # pylint: disable=import-outside-toplevel
        _is_disabled = is_plugin_disabled
    caller = sys._getframe(1).f_code.co_filename  # pylint: disable=protected-access
    dirname = _plugin_dirname_for_file(caller)
    if dirname and _is_disabled(dirname):
        return
    cron_register[job_name] = job_function
    plugin_register.append(job_name)
