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
    if not value:
        return False


def match(value, needle, condition, negate=False):
    """
    Check for Match for given params
    """
    try:
        # pylint: disable=too-many-branches, too-many-return-statements
        if condition == 'ignore' and negate:
            # In case that rule ignore is negate, than the condition simply not match
            return False

        if condition == 'ignore':
            return True

        if condition == 'bool':
            value = make_bool(value)
            needle = make_bool(needle)
        else:
            if isinstance(value, str):
                value = str(value).lower()
            needle = str(needle).lower()

        if negate:
            if condition == 'equal':
                if value != needle:
                    return True
            elif condition == 'in':
                if not isinstance(value, list):
                    value = str(value)
                if needle not in value:
                    return True
            elif condition == 'not_in':
                if not isinstance(value, list):
                    value = str(value)
                if needle in value:
                    return True
            elif condition == 'in_list':
                if not isinstance(needle, list):
                    needle = [x.strip() for x in needle.split(',')]
                if value not in needle:
                    return True
            elif condition == 'swith':
                if not str(value).startswith(needle):
                    return True
            elif condition == 'ewith':
                if not str(value).endswith(needle):
                    return True
            elif condition == 'regex':
                pattern = re.compile(needle) #@TODO Cache
                if not pattern.match(str(value)):
                    return True
            elif condition == 'bool':
                if needle != value:
                    return True

            return False

        if condition == 'equal':
            if value == needle:
                return True
        elif condition == 'in':
            if not isinstance(value, list):
                value = str(value)
            if needle in value:
                return True
        elif condition == 'not_in':
            if not isinstance(value, list):
                value = str(value)
            if needle not in value:
                return True
        elif condition == 'in_list':
            if not isinstance(needle, list):
                needle = [x.strip() for x in needle.split(',')]
            if value in needle:
                return True
        elif condition == 'swith':
            if str(value).startswith(needle):
                return True
        elif condition == 'ewith':
            if str(value).endswith(needle):
                return True
        elif condition == 'regex':
            pattern = re.compile(needle)
            if pattern.match(str(value)):
                return True
        elif condition == 'bool':
            if needle == value:
                return True
        return False
    except Exception as error:
        raise Exception(f"Condition Failed: {condition}, Value: {value}, Needed: {needle}. Hint: {error}")
