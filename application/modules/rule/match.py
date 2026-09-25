#!/usr/bin/env python3
"""
Helper To match condtions
"""
# pylint: disable=too-many-branches,too-many-return-statements
import datetime
import re


# Compiled regex cache. Rule conditions use the same needles across every
# host in a sync run, so re-compiling per call is pure overhead.
_REGEX_CACHE = {}

# Upper bound for user-supplied patterns. It only caps how much work a
# single compile can cost — a list of hostnames joined into one
# alternation is a legitimate pattern and easily passes a few thousand
# characters, so the limit has to leave room for it.
MAX_REGEX_LENGTH = 10000


def _compiled_regex(needle):
    """Return a compiled regex for `needle`, caching the result."""
    cached = _REGEX_CACHE.get(needle)
    if cached is not None:
        return cached
    if len(needle) > MAX_REGEX_LENGTH:
        raise re.error(
            f"Regex pattern is {len(needle)} characters long, "
            f"the maximum is {MAX_REGEX_LENGTH}")
    compiled = re.compile(needle)
    _REGEX_CACHE[needle] = compiled
    return compiled


# Conditions comparing a timestamp attribute against the clock instead of
# against another string. Everything that needs to know whether a rule can
# change its answer without the host changing asks for this tuple — see
# Rule.depends_on_time().
AGE_CONDITIONS = ('older_than', 'newer_than')

# Units accepted behind the age of those conditions. Without a unit the
# number counts days, which is what the Jinja expression these conditions
# replace compared ((utcnow() - syncer_last_seen).days > 2).
AGE_UNIT_SECONDS = {
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
}


class MatchException(Exception):
    """
    Invalid Match Exception
    """


def make_bool(value):
    """
    Make Bool from given object
    """
    if value is None:
        return False
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
    return False



def parse_age(needle):
    """
    The user's age as seconds: ``2d``, ``12h``, ``30m``, ``1w`` — or, with
    no unit behind it, that number of days.
    """
    text = str(needle).strip().lower()
    seconds_per_unit = AGE_UNIT_SECONDS['d']
    if text and text[-1] in AGE_UNIT_SECONDS:
        seconds_per_unit = AGE_UNIT_SECONDS[text[-1]]
        text = text[:-1].strip()
    try:
        amount = float(text)
    except ValueError:
        units = '/'.join(sorted(AGE_UNIT_SECONDS))
        raise ValueError(
            f"'{needle}' is not an age. Give a number of days, or a number "
            f"followed by one of {units} — like 2d, 12h, 30m, 1w") from None
    return amount * seconds_per_unit


def age_in_seconds(attr_value):
    """
    How long ago the attribute's point in time was, in seconds — or None
    when the value is not a point in time at all.

    The timestamps the syncer writes are naive UTC (see
    ``Host.set_import_seen``); a date imported from somewhere else may
    arrive as a string, with or without an offset. Everything is compared
    in UTC.
    """
    if isinstance(attr_value, datetime.datetime):
        stamp = attr_value
    else:
        try:
            stamp = datetime.datetime.fromisoformat(str(attr_value).strip())
        except (TypeError, ValueError):
            return None
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return (datetime.datetime.utcnow() - stamp).total_seconds()


def check_condition(attr_value, needle, condition):
    """
    Check the Condition Match
    """
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
    elif condition == 'string_in_list':
        if not isinstance(attr_value, list):
            attr_value = [x.strip() for x in attr_value.split(',')]
        if needle in attr_value:
            return True
    elif condition == 'in_list':
        # Warning, this condition needs a list given by
        # the user and checks if the attribute is in it
        if not isinstance(needle, list):
            needle = [x.strip() for x in needle.split(',')]
        if attr_value in needle:
            return True
    elif condition == 'swith':
        if attr_value.startswith(needle):
            return True
    elif condition == 'ewith':
        if attr_value.endswith(needle):
            return True
    elif condition == 'regex':
        pattern = _compiled_regex(needle)
        if pattern.match(str(attr_value)):
            return True
    elif condition in AGE_CONDITIONS:
        age = age_in_seconds(attr_value)
        if age is None:
            # Nothing to hold against the clock, so neither direction
            # matches: a host without a sighting date is out of both the
            # "not seen for two days" and the "seen today" rule.
            return False
        limit = parse_age(needle)
        if condition == 'older_than':
            return age > limit
        return age <= limit
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
