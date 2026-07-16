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


def project_allows_account(project, account_name):
    """
    True when a Project's rules (and assigned hosts) may be
    exported to ``account_name``: not on the project's ``deny_by_accounts``
    list, and either no ``limit_by_accounts`` allow list is set or the
    account is on it. The deny list wins over the allow list.

    Lives here (not on the model) so the account-scope decision is shared
    by the rule exports, the host export and the model without importing
    MongoEngine documents.
    """
    denied = [name for name in (getattr(project, 'deny_by_accounts', None) or [])
              if name]
    if account_name in denied:
        return False
    allowed = [name for name in (getattr(project, 'limit_by_accounts', None) or [])
               if name]
    return not allowed or account_name in allowed
