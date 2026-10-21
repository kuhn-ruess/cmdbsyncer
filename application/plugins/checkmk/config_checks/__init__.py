"""
Checkmk configuration checks.

Each check reads part of a Checkmk site's setup over the REST API and returns
a list of problems found in it. The checks only read, they never change,
delete or activate anything in Checkmk.

A check is a subclass of :class:`ConfigCheck` registered with
:func:`register_check`. The GUI lists every registered check, so adding a
check means: write a module next to ``httpv2.py``, decorate the class with
``@register_check`` and import the module at the bottom of this file.
"""
from .base import (
    Column, ConfigCheck, Finding, Topic, fetch_rules, describe_conditions)

_CHECKS = {}


def register_check(check_class):
    """Class decorator: make ``check_class`` available under its ``name``."""
    if not check_class.name:
        raise ValueError(f"{check_class.__name__} has no name")
    if check_class.name in _CHECKS:
        raise ValueError(f"Config check '{check_class.name}' registered twice")
    _CHECKS[check_class.name] = check_class
    return check_class


def get_checks():
    """Every registered check class, ordered by title."""
    return sorted(_CHECKS.values(), key=lambda check: check.title.lower())


def get_check(name):
    """The registered check class called ``name``, or None."""
    return _CHECKS.get(name)


PDF_PACKAGE = 'fpdf2'
PDF_MISSING = (f"The PDF export needs the Python package {PDF_PACKAGE}: "
               f"pip install {PDF_PACKAGE} (part of cmdbsyncer[extras])")


def pdf_available():
    """Whether the optional PDF library can be imported."""
    try:
        import fpdf  # pylint: disable=import-outside-toplevel,unused-import
    except ImportError:
        return False
    return True


def run_checks(account_name, names):
    """
    Run the checks called ``names`` against ``account_name`` with one shared
    Checkmk connection and return their reports in the given order. Unknown
    names are skipped.
    """
    # pylint: disable=import-outside-toplevel
    from ..cmk2 import CMK2
    checks = [_CHECKS[name]() for name in names if name in _CHECKS]
    if not checks:
        return []
    cmk = CMK2(account_name)
    return [check.run(cmk, account_name) for check in checks]


# Built-in checks register themselves on import.
# pylint: disable=wrong-import-position,cyclic-import
from . import httpv2  # noqa: E402,F401

__all__ = ['Column', 'ConfigCheck', 'Finding', 'Topic', 'fetch_rules', 'describe_conditions',
           'register_check', 'get_checks', 'get_check', 'run_checks',
           'pdf_available', 'PDF_MISSING']
