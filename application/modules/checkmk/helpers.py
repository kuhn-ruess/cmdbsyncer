"""
Checkmk Helpers
"""
import re
import app

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
    Cleans Invalid Chars out
    of strings you wan't to use as tag_id in cmk
    """
    if app.config['CMK_JINJA_USE_REPLACERS_FOR_HOSTNAMES']:
        for needle, replacer in app.config['REPLACERS']:
            input_str = input_str.replace(needle, replacer)
    return re.sub('[^a-zA-Z0-9_-]', '_', input_str.strip()).lower()
