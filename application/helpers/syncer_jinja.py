"""
Syncers Jinja Functions
"""
#pylint: disable=logging-fstring-interpolation
import ast
import ipaddress
import jinja2
from jinja2 import StrictUndefined

from application import logger
from application.modules.checkmk.helpers import cmk_cleanup_tag_id, cmk_cleanup_hostname



def syncer_eval(string, default=None):
    """
    Evals given object
    """
    try:
        return ast.literal_eval(string)
    except ValueError:
        return default

def syncer_defined(string, default=""):
    """
    Makes String Object True or False
    """
    if string.lower() in ["false", "none"]:
        return default
    if not string:
        return default
    return string

def get_ip4_network(ip_string):
    """
    Converts 192.178.2.55/255.255.255.0 to 192.178.2.0/24
    """
    net = ipaddress.ip_interface(ip_string)
    return net.network

def get_ip4_interface(ip_string):
    """
    Converts 192.178.2.55/255.255.255.0 to 192.178.2.55/24
    """
    net = ipaddress.ip_interface(ip_string)
    return net

def get_list(input_list):
    """
    Convert a List which is a
    string to real object
    """
    try:
        if isinstance(input_list, str):
            input_list = ast.literal_eval(input_list.replace('\n',''))
        return input_list
    except ValueError:
        return []

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


def render_jinja(value, mode="ignore", replace_newlines=True, **kwargs):
    """
    Render given string

    mode:
    - ignore: Just ingnore missing Variables
    - raise: Raise Error if missing Variables
    - nullify: Nullify string in nase of missing Variables
    """
    logger.debug(f"JINJA: Rewrite String: {value}")
    payload = {}

    if replace_newlines:
        value = value.replace('\n','')
        logger.debug(f"JINJA: Replaced Newlines: {value}")

    if mode in ["raise", "nullify"]:
        #value_tpl.undefined = StrictUndefined
        payload['undefined'] = StrictUndefined
        logger.debug("JINJA: Strict Undefined defined")


    value_tpl = jinja2.Template(str(value), **payload)
    value_tpl.globals.update({
        'get_list': get_list,
        'merge_list_of_dicts': merge_list_of_dicts,
        'cmk_cleanup_tag_id': cmk_cleanup_tag_id,
        'cmk_cleanup_hostname': cmk_cleanup_hostname,
        'get_ip4_network': get_ip4_network,
        'get_ip4_interface': get_ip4_interface,
        'eval': syncer_eval,
        'defined': syncer_defined,

    })


    if mode == 'nullify':
        try:
            final =  value_tpl.render(**kwargs)
        except (jinja2.exceptions.UndefinedError, TypeError):
            logger.debug("JINJA Exception: String full nullifyed")
            return ""
        except SyntaxError as exc:
            logger.debug(f"Jinja Exception: Syntax error: {exc}")
            return ""
    else:
        final = value_tpl.render(**kwargs)
    logger.debug(f"JINJA: String After Rewrite: {final}")
    return final
