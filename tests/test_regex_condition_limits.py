"""Long regex patterns and the messages users get when one is rejected.

A list of hostnames joined into one alternation is a normal pattern —
32 FQDNs already pass 1000 characters. It has to run, and when a
pattern really is rejected the user has to hear about it instead of
looking at an empty result.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import unittest
from unittest.mock import patch

from application.modules.rule.match import (
    MAX_REGEX_LENGTH,
    MatchException,
    match,
)
from application.views import host_filters


def _alternation(count, name_length=31):
    """`count` distinct FQDN-ish names joined into one alternation."""
    names = [f"fmg-srv-app{i:03d}".ljust(name_length, 'x') for i in range(count)]
    return names, '(' + '|'.join(names) + ')'


class _Query:  # pylint: disable=too-few-public-methods
    """Records the kwargs the filter hands to the mongoengine query."""

    def __init__(self):
        self.applied = None

    def filter(self, **kwargs):
        self.applied = kwargs
        return self


class RegexConditionLengthTest(unittest.TestCase):
    """application.modules.rule.match"""

    def test_thirty_two_names_still_match(self):
        names, pattern = _alternation(32)
        self.assertGreater(len(pattern), 1000)
        self.assertTrue(match(names[0], pattern, 'regex'))
        self.assertTrue(match(names[31], pattern, 'regex'))
        self.assertFalse(match('some-other-host', pattern, 'regex'))

    def test_pattern_at_the_limit_is_accepted(self):
        pattern = 'a' * MAX_REGEX_LENGTH
        self.assertTrue(match(pattern, pattern, 'regex'))

    def test_pattern_over_the_limit_names_its_length(self):
        pattern = 'a' * (MAX_REGEX_LENGTH + 1)
        with self.assertRaises(MatchException) as caught:
            match('anything', pattern, 'regex')
        message = str(caught.exception)
        self.assertIn(str(MAX_REGEX_LENGTH + 1), message)
        self.assertIn(str(MAX_REGEX_LENGTH), message)


class HostnameRegexFilterTest(unittest.TestCase):
    """application.views.host_filters.FilterHostnameRegex"""

    def setUp(self):
        self.flt = host_filters.FilterHostnameRegex.__new__(
            host_filters.FilterHostnameRegex)

    def _apply(self, value):
        query = _Query()
        with patch.object(host_filters, 'flash') as flash:
            self.flt.apply(query, value)
        return query.applied, flash.call_args

    def test_long_alternation_reaches_the_query(self):
        _names, pattern = _alternation(32)
        applied, flashed = self._apply(pattern)
        self.assertEqual(applied['hostname'].pattern, pattern)
        self.assertIsNone(flashed)

    def test_too_long_pattern_flashes_instead_of_matching_nothing(self):
        applied, flashed = self._apply('a' * (MAX_REGEX_LENGTH + 1))
        self.assertEqual(applied, {'hostname': None})
        self.assertEqual(flashed.args[1], 'danger')
        self.assertIn(str(MAX_REGEX_LENGTH), flashed.args[0])

    def test_invalid_pattern_flashes_the_regex_error(self):
        applied, flashed = self._apply('(unbalanced')
        self.assertEqual(applied, {'hostname': None})
        self.assertEqual(flashed.args[1], 'danger')
        self.assertIn('Invalid regular expression', flashed.args[0])
