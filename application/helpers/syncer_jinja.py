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
from application.helpers.get_account import get_account_variable


JINJA_ENV = SandboxedEnvironment(autoescape=True)

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

def get_list(input_list):
    """
    Convert a List which is a
    string to real object
    """
    if isinstance(input_list, list):
        return input_list
    if isinstance(input_list, tuple):
        return list(input_list)
    if isinstance(input_list, str):
        # fix malformated inputs:
        if input_list.endswith(','):
            input_list = input_list[:-1]
        try:
            # Try a string witch looks like a list
            input_list = ast.literal_eval(input_list.replace('\n',''))
        except (ValueError, SyntaxError):
            input_list = [x.strip() for x in input_list.split(',') if x ]
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


_GLOBALS = {
    'get_list': get_list,
    'merge_list_of_dicts': merge_list_of_dicts,
    'cmk_cleanup_tag_id': _cmk_cleanup_tag_id,
    'cmk_cleanup_hostname': _cmk_cleanup_hostname,
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


def render_jinja(value, mode="ignore", replace_newlines=True, **kwargs):
    """
    Render given string

    mode:
    - ignore: Just ingnore missing Variables
    - raise: Raise Error if missing Variables
    - nullify: Nullify string in nase of missing Variables
    """
    # Process ACCOUNT variables anywhere in the string
    if isinstance(value, str) and '{{ACCOUNT:' in value:
        value = re.sub(r'\{\{ACCOUNT:[^}]+\}\}', replace_account_variable, value)

    if replace_newlines and isinstance(value, str):
        value = value.replace('\n', '')

    source = str(value)
    strict = mode in ("raise", "nullify")
    value_tpl = _compile_template(source, strict)

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
