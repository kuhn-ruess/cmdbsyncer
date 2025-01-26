#!/usr/bin/env python3
"""
Helper To match condtions
"""
import re


class MatchException(Exception):
    """
    Invalid Match Exception
    """


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



def check_condition(attr_value, needle, condition):
    """
    Check the Condition Match
    """
    # pylint: disable=too-many-branches, too-many-return-statements
    if condition == 'equal':
        if attr_value == needle:
            return True
    elif condition == 'in':
        # In String
        if needle in attr_value:
            return True
    elif condition == 'not_in':
        # Not in String
        if needle not in attr_value:
            return True
    elif condition == 'in_list':
        if not isinstance(attr_value, list):
            attr_value = [x.strip() for x in attr_value.split(',')]
        if needle in attr_value:
            return True
    elif condition == 'swith':
        if attr_value.startswith(needle):
            return True
    elif condition == 'ewith':
        if attr_value.endswith(needle):
            return True
    elif condition == 'regex':
        pattern = re.compile(needle)
        if pattern.match(str(attr_value)):
            return True
    elif condition == 'bool':
        if needle == attr_value:
            return True
    return False


def match(attr_value, needle, condition, negate=False):
    """
    Check for Match for given params
    """
    try:
        if condition == 'ignore' and negate:
            # In case that rule ignore is negate, than the condition simply not match
            return False

        if condition == 'ignore':
            return True

        if condition == 'bool':
            attr_value = make_bool(attr_value)
            needle = make_bool(needle)

        if condition in ['equal', 'in', 'not_in', 'swith', 'ewith']:
            ### Conditions which are String matches
            attr_value = str(attr_value).lower()
            needle = str(needle).lower()

        result = check_condition(attr_value, needle, condition)

        if negate and result:
            return False
        if negate and not result:
            return True
        return result

    except Exception as error:
        raise MatchException(f"Condition Failed: {condition}, "\
                             f"Attributes Value: {attr_value}, "\
                             f"Needed: {needle}. Hint: {error}") from error
