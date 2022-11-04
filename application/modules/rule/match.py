#!/usr/bin/env python3
"""
Helper To match condtions
"""
import re


# pylint: disable=inconsistent-return-statements
def make_bool(value):
    """
    Make Bool from given object
    """
    if isinstance(value, bool):
        return value
    if value.lower() == 'false':
        return False
    if value.lower() == 'true':
        return True
    if value.lower() == 'none':
        return False


def match(value, needle, condition, negate=False):
    """
    Check for Match for given params
    """
    # pylint: disable=too-many-branches, too-many-return-statements
    if condition == 'ignore':
        return True
    if condition == 'bool':
        value = make_bool(value)
        needle = make_bool(needle)
    if isinstance(value, int) and value:
        value = str(value)
    if isinstance(needle, int) and needle:
        needle = str(needle)
    if not isinstance(value, bool) and value:
        value = value.lower()
    if not isinstance(needle, bool) and needle:
        needle = needle.lower()
    if negate:
        if condition == 'equal':
            if value != needle:
                return True
        elif condition == 'in':
            if needle not in value:
                return True
        elif condition == 'in_list':
            if value not in [x.strip() for x in needle.split(',')]:
                return True
        elif condition == 'swith':
            if not value.startswith(needle):
                return True
        elif condition == 'ewith':
            if not value.endswith(needle):
                return True
        elif condition == 'regex':
            pattern = re.compile(needle) #@TODO Cache
            if not pattern.match(value):
                return True
        elif condition == 'bool':
            if needle != value:
                return True

        return False

    if condition == 'equal':
        if value == needle:
            return True
    elif condition == 'in':
        if needle in value:
            return True
    elif condition == 'in_list':
        if value in [x.strip() for x in needle.split(',')]:
            return True
    elif condition == 'swith':
        if value.startswith(needle):
            return True
    elif condition == 'ewith':
        if value.endswith(needle):
            return True
    elif condition == 'regex':
        pattern = re.compile(needle) #@TODO Cache
        if pattern.match(value):
            return True
    elif condition == 'bool':
        if needle == value:
            return True
    return False
