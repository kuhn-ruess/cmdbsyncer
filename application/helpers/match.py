#!/usr/bin/env python3
"""
Helper To match condtions
"""
import re


def match(value, needle, condition, negate=False):
    """
    Check for Match for given params
    """
    # pylint: disable=too-many-branches, too-many-return-statements
    if condition == 'ignore':
        return True
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
    return False
