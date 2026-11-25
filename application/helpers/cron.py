"""
Cron Job Managment Helper
"""
import os
import sys
from application import cron_first, cron_register, plugin_register

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


# Plugin directory each cron job was registered from, "" for none
cron_plugin_dir = {}


def _caller_plugin():
    """
    Plugin directory of the code which called the register function and
    whether that plugin is disabled
    """
    global _is_disabled  # pylint: disable=global-statement
    if _is_disabled is None:
        from application.helpers.plugins import is_plugin_disabled  # pylint: disable=import-outside-toplevel
        _is_disabled = is_plugin_disabled
    caller = sys._getframe(2).f_code.co_filename  # pylint: disable=protected-access
    dirname = _plugin_dirname_for_file(caller)
    return dirname, bool(dirname and _is_disabled(dirname))


def register_cronjob(job_name, job_function, first=False):
    """
    Register Cronjob to the System

    Pass the Unqiue Name and the Function reference. With first, the job
    leads the list of commands in the cron group form.
    """
    dirname, disabled = _caller_plugin()
    if disabled:
        return
    cron_plugin_dir[job_name] = dirname
    if first:
        cron_first.add(job_name)
    cron_register[job_name] = job_function
    plugin_register.append(job_name)


# The import and inventorize functions of each account type:
# {account_type: [{'import': function, 'inventorize': function}]}, the first
# entry is what Run Jobs defined by Account runs for an account without jobs
import_register = {}


def register_import(account_type, import_function=None, inventorize_function=None):
    """
    Register an import and inventorize of a plugin for accounts of the
    type: tells which of its jobs import and which inventorize, the first
    registered is run for an account that lists no jobs.
    """
    if _caller_plugin()[1]:
        return
    import_register.setdefault(account_type, []).append({
        'import': import_function,
        'inventorize': inventorize_function,
    })
