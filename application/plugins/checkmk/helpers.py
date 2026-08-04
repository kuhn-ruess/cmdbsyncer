"""
Checkmk Helpers
"""
import re
from application import app

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
