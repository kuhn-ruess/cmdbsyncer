"""
Checkmk Helpers
"""
import re
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from application import app
from application.helpers.syncer_jinja import render_jinja, get_list


def make_progress():
    """Return the Syncer's standard rich Progress bar."""
    return Progress(SpinnerColumn(),
                    MofNCompleteColumn(),
                    *Progress.get_default_columns(),
                    TimeElapsedColumn())

def cmk_cleanup_tag_id(input_str):
    """
    Cleans Invalid Chars out
    of strings you wan't to use as tag_id in cmk
    """
    if app.config['CMK_JINJA_USE_REPLACERS']:
        for needle, replacer in app.config['REPLACERS']:
            input_str = input_str.replace(needle, replacer)
    return re.sub('[^a-zA-Z0-9_-]', '_', input_str.strip()).lower()

def cmk_cleanup_tag_value(input_str):
    """
    Cleans invalid Chars in Label/ Tag Values
    """
    if app.config['CMK_JINJA_USE_REPLACERS']:
        for needle, replacer in app.config['REPLACERS']:
            input_str = input_str.replace(needle, replacer)
    return re.sub('[^a-zA-Z0-9_-]', '_', input_str.strip()).lower()


def cmk_cleanup_hostname(input_str):
    """
    Cleans Invalid Chars out of Hostnames
    """
    if app.config['CMK_JINJA_USE_REPLACERS_FOR_HOSTNAMES']:
        for needle, replacer in app.config['REPLACERS']:
            input_str = input_str.replace(needle, replacer)
    return re.sub('[^a-zA-Z0-9_-]', '_', input_str.strip()).lower()


def project_allows_account(project, account_name, kind='host'):
    """
    True when a Project's members of ``kind`` ('host' or 'rule') may be
    exported to ``account_name``: not on the applicable deny list, and
    either no allow list is set or the account is on it. The deny list
    wins over the allow list.

    Hosts and rules are steered separately. ``kind='host'`` uses
    ``limit_by_accounts`` / ``deny_by_accounts``; ``kind='rule'`` uses
    ``rule_limit_by_accounts`` / ``rule_deny_by_accounts`` and falls back
    to the host list per side when the rule list is empty — a project
    that only fills the host lists keeps steering its rules the same way.

    Lives here (not on the model) so the account-scope decision is shared
    by the rule exports, the host export and the model without importing
    MongoEngine documents.
    """
    def _names(attr):
        return [name for name in (getattr(project, attr, None) or []) if name]

    if kind == 'rule':
        denied = _names('rule_deny_by_accounts') or _names('deny_by_accounts')
        allowed = _names('rule_limit_by_accounts') or _names('limit_by_accounts')
    else:
        denied = _names('deny_by_accounts')
        allowed = _names('limit_by_accounts')

    if account_name in denied:
        return False
    return not allowed or account_name in allowed


def resolve_loop_list(list_to_loop, attributes):
    """
    Resolve the "Loop over" field of an outcome into its entries.

    A single brace decides how the value is read. Without one it is a
    plain host attribute name — the only spelling this field ever
    accepted — and is looked up in the host's attributes unchanged.
    With one it is a Jinja template rendered against those attributes,
    like the list field of the notification export, so the entries can
    be built, filtered or combined instead of having to exist as an
    attribute of their own. Both spellings end in ``get_list``, which
    also splits a plain comma separated string.

    Returns ``(entries, error)``; ``error`` carries the message when the
    Jinja could not be rendered.
    """
    if not list_to_loop:
        return [], None
    if '{' in list_to_loop:
        try:
            rendered = render_jinja(list_to_loop, _ctx=attributes)
        except Exception as exp:  # pylint: disable=broad-except
            return [], f"{type(exp).__name__}: {exp}"
    else:
        # .get, not [] — an attribute not every host carries must not
        # abort the whole export with a KeyError.
        rendered = attributes.get(list_to_loop, '')
    return [x for x in get_list(rendered) if x], None
