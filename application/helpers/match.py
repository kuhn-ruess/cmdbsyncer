#!/usr/bin/env python3
"""
Helper To match condtions
"""


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
        elif condition == 'swith':
            if not value.startswith(needle):
                return True
        elif condition == 'ewith':
            if not value.endswith(needle):
                return True
        return False
    if condition == 'equal':
        if value == needle:
            return True
    elif condition == 'in':
        if needle in value:
            return True
    elif condition == 'swith':
        if value.startswith(needle):
            return True
    elif condition == 'ewith':
        if value.endswith(needle):
            return True
    return False
