"""
Syncers Jinja Functions
"""
# pylint: disable=import-outside-toplevel,logging-fstring-interpolation
# pylint: disable=missing-function-docstring
import ast
import datetime
import ipaddress
import re
import jinja2
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from application import logger
from application.helpers.label_hash import syncer_hash
from application.helpers.get_account import get_account_variable


# render_jinja renders data values (rule conditions, regex patterns,
# config payloads, passwords) that are sent to external APIs — never
# inserted into HTML. Autoescaping here turns regex/config characters
# (`&`, `<`, `>`, `'`, `"`) into HTML entities and breaks rule
# conditions sent to Checkmk. HTML contexts do their own escaping via
# Flask/Jinja at template render time.
JINJA_ENV = SandboxedEnvironment(autoescape=False)

# Template objects are expensive to build (parse + compile) and
# immutable afterwards, so we memoize by (mode, source). Two separate
# envs so StrictUndefined and the default undefined don't collide.
_STRICT_ENV = JINJA_ENV.overlay()
_TEMPLATE_CACHE = {}

def _cmk_cleanup_tag_id(value):
    """
    Lazily import the Checkmk helper to avoid circular imports while still
    exposing the cleanup function to Jinja templates.
    """
    from application.plugins.checkmk.helpers import cmk_cleanup_tag_id as _cleanup

    return _cleanup(value)


def _cmk_cleanup_hostname(value):
    """
    Lazily import the Checkmk helper to avoid circular imports while still
    exposing the cleanup function to Jinja templates.
    """
    from application.plugins.checkmk.helpers import cmk_cleanup_hostname as _cleanup

    return _cleanup(value)


def _cmk_password(name):
    """
    Resolve a syncer Checkmk Password name to its password-store ident
    (``cmdbsyncer_<id>``) so rules can reference a stored secret instead of an
    inlined one. Lazily imported to avoid circular imports.
    """
    from application.plugins.checkmk.rule_passwords import password_ident

    return password_ident(name)


def syncer_eval(string, default=None):
    """
    Evals given object
    """
    if isinstance(string, str):
        try:
            return ast.literal_eval(string)
        except ValueError:
            return default
    else:
        return string

def syncer_defined(string, default=""):
    """
    Makes String Object True or False
    """
    if isinstance(string, bool):
        return string
    if string.lower() in ["false", "none"]:
        return default
    if not string:
        return default
    return string

def get_ip_network(ip_string):
    """
    Converts 192.178.2.55/255.255.255.0 to 192.178.2.0/24
    """
    if not ip_string:
        return ''
    net = ipaddress.ip_network(ip_string.strip(), strict=False)
    net_part = ip_string.split('/')[1]
    return f"{net.network_address}/{net_part}"

def get_ip_interface(ip_string):
    """
    Converts 192.178.2.55/255.255.255.0 to 192.178.2.55/24
    """
    if not ip_string:
        return ''
    net = ipaddress.ip_interface(ip_string.strip())
    return net

def _string_to_list(input_list):
    """
    The entries a string holds: a Python list literal, or comma separated.
    """
    # fix malformated inputs:
    if input_list.endswith(','):
        input_list = input_list[:-1]
    try:
        # Try a string witch looks like a list
        parsed = ast.literal_eval(input_list.replace('\n',''))
    except (ValueError, SyntaxError):
        return [x.strip() for x in input_list.split(',') if x ]
    if isinstance(parsed, (list, tuple)):
        return list(parsed)
    # A literal that is not a list at all: a single quoted entry
    # ('"web",' — what a {% for %} loop writing quoted entries produces
    # for a one element list) or a number. Handing that back unchanged
    # made the caller iterate a string letter by letter.
    return [parsed]


def get_list(input_list):
    """
    Convert a List which is a
    string to real object

    A missing attribute is a list of nothing: Jinja hands an undefined
    variable in here, and returning it unchanged made the caller fail
    on the next operation — a template that merely names an attribute
    not every host carries would take the whole rule down with it.
    """
    if input_list is None or isinstance(input_list, jinja2.Undefined):
        return []
    if isinstance(input_list, list):
        return input_list
    if isinstance(input_list, tuple):
        return list(input_list)
    if isinstance(input_list, str):
        return _string_to_list(input_list)
    return input_list


def merge_list_of_dicts(input_list):
    """
    Merge a list of dicts to single dict
    """
    if isinstance(input_list, str):
        try:
            input_list = ast.literal_eval(input_list.replace('\n',''))
        except ValueError:
            return {}
    if not input_list:
        return {}
    dict_obj = {k: v for d in input_list for k, v in d.items() if v}
    return dict_obj

def replace_account_variable(match):
    account_var = match.group(0)
    try:
        return get_account_variable(account_var)
    except ValueError:
        return account_var


# Filters have to be registered on both envs — an overlay copies the
# filter map at creation time, it does not keep following the parent.
for _env in (JINJA_ENV, _STRICT_ENV):
    _env.filters['hash'] = syncer_hash


_GLOBALS = {
    'get_list': get_list,
    'hash_value': syncer_hash,
    'merge_list_of_dicts': merge_list_of_dicts,
    'cmk_cleanup_tag_id': _cmk_cleanup_tag_id,
    'cmk_cleanup_hostname': _cmk_cleanup_hostname,
    'cmk_password': _cmk_password,
    'get_ip_network': get_ip_network,
    'get_ip4_interface': get_ip_interface,
    'get_ip_interface': get_ip_interface,
    'eval': syncer_eval,
    'defined': syncer_defined,
    'datetime': datetime,
}


def _compile_template(source, strict):
    """
    Compile and cache a template. Sync runs reuse the same handful of
    rule templates across every host, so caching keeps the expensive
    parse+compile step off the hot path.
    """
    key = (strict, source)
    cached = _TEMPLATE_CACHE.get(key)
    if cached is not None:
        return cached
    env = _STRICT_ENV if strict else JINJA_ENV
    tpl = env.from_string(source)
    tpl.globals.update(_GLOBALS)
    _TEMPLATE_CACHE[key] = tpl
    return tpl


# Use StrictUndefined on the strict env so undefined variables surface
# as `UndefinedError` the same way the old overlay did.
_STRICT_ENV.undefined = StrictUndefined


# {{ACCOUNT:name:field}} macros are resolved before Jinja ever compiles;
# their bare colons are not valid Jinja, so they get neutralised before a
# syntax check looks at a template.
_ACCOUNT_MACRO_RE = re.compile(r'\{\{\s*ACCOUNT:[^}]+\}\}')


def check_jinja_syntax(value):
    """
    Compile a template without rendering it and report a syntax error.

    A template that does not compile renders to an empty string in every
    mode, so whatever it was meant to fill is silently lost at export
    time. Checking it while the value is being saved (or before a run
    starts) turns that into a visible error.

    Returns the error message, or None when the value compiles or holds
    no template at all.
    """
    if not isinstance(value, str) or not value:
        return None
    if '{{' not in value and '{%' not in value:
        return None
    try:
        JINJA_ENV.from_string(_ACCOUNT_MACRO_RE.sub('x', value))
    except jinja2.exceptions.TemplateSyntaxError as exc:
        return exc.message
    return None


def render_jinja(value, mode="ignore", replace_newlines=True, **kwargs):
    """
    Render given string

    mode:
    - ignore: Just ingnore missing Variables
    - raise: Raise Error if missing Variables
    - nullify: Nullify string in nase of missing Variables
    """
    # Process ACCOUNT variables anywhere in the string. Whitespace after
    # `{{`, around the colons and before `}}` is tolerated so the natural
    # Jinja spelling `{{ ACCOUNT:name:field }}` resolves like the compact
    # `{{ACCOUNT:name:field}}`.
    if isinstance(value, str) and 'ACCOUNT:' in value:
        value = re.sub(r'\{\{\s*ACCOUNT:[^}]+\}\}', replace_account_variable, value)

    if replace_newlines and isinstance(value, str):
        value = value.replace('\n', '')

    source = str(value)
    strict = mode in ("raise", "nullify")
    try:
        value_tpl = _compile_template(source, strict)
    except jinja2.exceptions.TemplateSyntaxError as exc:
        # A malformed template — e.g. an {{ACCOUNT:...}} macro whose
        # account no longer exists, so it survived substitution and reaches
        # Jinja with its literal colons — must not 500 the caller (debug
        # page, inventory export). Only explicit 'raise' mode propagates.
        if mode == 'raise':
            raise
        logger.debug(f"Jinja Exception: Syntax error in {value!r}: {exc}")
        return ""

    if mode == 'nullify':
        try:
            final = value_tpl.render(**kwargs)
        except (jinja2.exceptions.UndefinedError, TypeError):
            logger.debug(f"JINJA Exception: String {value} full nullifyed")
            return ""
        except SyntaxError as exc:
            logger.debug(f"Jinja Exception: Syntax error: {exc}")
            return ""
    else:
        final = value_tpl.render(**kwargs)
    return final.strip()
