"""
Unit tests for the rule matching engine.

Covers:
  - application.modules.rule.match.check_condition (pure condition dispatch)
  - application.modules.rule.match.match (negation, type coercion, errors)
  - application.modules.rule.match.make_bool
  - application.modules.rule.match.parse_age / age_in_seconds and the
    "older than" / "newer than" conditions built on them
"""
# pylint: disable=missing-function-docstring
import datetime
import unittest

import re

from application.modules.rule.match import (
    check_condition,
    match,
    make_bool,
    parse_age,
    age_in_seconds,
    MatchException,
    MAX_REGEX_LENGTH,
    _compiled_regex,
)


class TestMakeBool(unittest.TestCase):
    """make_bool normalizes mixed user input into booleans."""

    def test_true_bool(self):
        self.assertTrue(make_bool(True))

    def test_false_bool(self):
        self.assertFalse(make_bool(False))

    def test_true_string(self):
        self.assertTrue(make_bool("true"))
        self.assertTrue(make_bool("True"))
        self.assertTrue(make_bool("TRUE"))

    def test_false_string(self):
        self.assertFalse(make_bool("false"))
        self.assertFalse(make_bool("False"))

    def test_none_string(self):
        self.assertFalse(make_bool("none"))

    def test_none_value(self):
        self.assertFalse(make_bool(None))

    def test_empty_string(self):
        self.assertFalse(make_bool(""))


class TestCheckCondition(unittest.TestCase):
    """check_condition performs the raw condition evaluation with no coercion."""

    # -- equal --

    def test_equal_hit(self):
        self.assertTrue(check_condition("prod", "prod", "equal"))

    def test_equal_miss(self):
        self.assertFalse(check_condition("prod", "dev", "equal"))

    # -- in / not_in (substring) --

    def test_in_substring_hit(self):
        self.assertTrue(check_condition("webserver01", "server", "in"))

    def test_in_substring_miss(self):
        self.assertFalse(check_condition("webserver01", "database", "in"))

    def test_not_in_substring_hit(self):
        self.assertTrue(check_condition("webserver01", "database", "not_in"))

    def test_not_in_substring_miss(self):
        self.assertFalse(check_condition("webserver01", "server", "not_in"))

    # -- string_in_list: needle in attr_value (list-ish) --

    def test_string_in_list_from_list(self):
        self.assertTrue(check_condition(["linux", "prod"], "linux", "string_in_list"))

    def test_string_in_list_from_csv_string(self):
        self.assertTrue(check_condition("linux, prod, web", "prod", "string_in_list"))

    def test_string_in_list_miss(self):
        self.assertFalse(check_condition(["linux", "prod"], "windows", "string_in_list"))

    # -- in_list: attr_value in user-supplied list --

    def test_in_list_csv_needle(self):
        self.assertTrue(check_condition("prod", "prod, dev, stage", "in_list"))

    def test_in_list_actual_list(self):
        self.assertTrue(check_condition("prod", ["prod", "dev"], "in_list"))

    def test_in_list_miss(self):
        self.assertFalse(check_condition("qa", "prod, dev", "in_list"))

    # -- swith / ewith --

    def test_starts_with(self):
        self.assertTrue(check_condition("web-01", "web", "swith"))
        self.assertFalse(check_condition("db-01", "web", "swith"))

    def test_ends_with(self):
        self.assertTrue(check_condition("host.example.com", ".com", "ewith"))
        self.assertFalse(check_condition("host.example.org", ".com", "ewith"))

    # -- regex --

    def test_regex_hit(self):
        self.assertTrue(check_condition("web-01", r"web-\d+", "regex"))

    def test_regex_miss(self):
        self.assertFalse(check_condition("db-01", r"web-\d+", "regex"))

    def test_regex_coerces_non_string_attr(self):
        self.assertTrue(check_condition(42, r"\d+", "regex"))

    # -- bool --

    def test_bool_equal(self):
        self.assertTrue(check_condition(True, True, "bool"))
        self.assertFalse(check_condition(True, False, "bool"))

    # -- unknown condition --

    def test_unknown_condition_returns_false(self):
        self.assertFalse(check_condition("a", "a", "definitely_not_a_real_condition"))


class TestMatchNegationAndCoercion(unittest.TestCase):
    """match wraps check_condition with negation and lowercase/bool coercion."""

    # -- ignore condition: special cased --

    def test_ignore_without_negate_always_matches(self):
        self.assertTrue(match("anything", "whatever", "ignore"))

    def test_ignore_with_negate_never_matches(self):
        self.assertFalse(match("anything", "whatever", "ignore", negate=True))

    # -- string conditions are case-insensitive via match() --

    def test_equal_is_case_insensitive(self):
        self.assertTrue(match("PROD", "prod", "equal"))
        self.assertTrue(match("prod", "PROD", "equal"))

    def test_in_is_case_insensitive(self):
        self.assertTrue(match("WebServer01", "server", "in"))

    def test_swith_is_case_insensitive(self):
        self.assertTrue(match("Web-01", "WEB", "swith"))

    def test_ewith_is_case_insensitive(self):
        self.assertTrue(match("HOST.EXAMPLE.COM", ".com", "ewith"))

    # -- regex stays case-sensitive (not in the lowercase list) --

    def test_regex_stays_case_sensitive(self):
        self.assertFalse(match("WEB-01", r"web-\d+", "regex"))
        self.assertTrue(match("web-01", r"web-\d+", "regex"))

    # -- negation flips the result --

    def test_negate_flips_hit_to_miss(self):
        self.assertFalse(match("prod", "prod", "equal", negate=True))

    def test_negate_flips_miss_to_hit(self):
        self.assertTrue(match("prod", "dev", "equal", negate=True))

    def test_negate_with_regex(self):
        self.assertFalse(match("web-01", r"web-\d+", "regex", negate=True))
        self.assertTrue(match("db-01", r"web-\d+", "regex", negate=True))

    # -- bool coercion before comparison --

    def test_bool_with_string_true(self):
        self.assertTrue(match("true", "True", "bool"))

    def test_bool_with_string_false_vs_true(self):
        self.assertFalse(match("false", "true", "bool"))

    def test_bool_with_none_and_false(self):
        # make_bool(None) -> False, make_bool('false') -> False
        self.assertTrue(match(None, "false", "bool"))

    # -- errors get wrapped in MatchException --

    def test_invalid_regex_raises_match_exception(self):
        with self.assertRaises(MatchException) as ctx:
            match("web-01", r"[unclosed", "regex")
        # Error message mentions the condition and values for debuggability
        self.assertIn("regex", str(ctx.exception))


class TestMatchRealWorldScenarios(unittest.TestCase):
    """End-to-end scenarios mirroring how the rule engine calls match()."""

    def test_host_in_prod_tag_group(self):
        # Attribute "environment" equals "prod"
        self.assertTrue(match("prod", "prod", "equal"))

    def test_host_not_in_excluded_list(self):
        # Attribute value NOT in a user-supplied list
        self.assertFalse(match("qa", "prod, dev", "in_list", negate=True) is False
                         and match("qa", "prod, dev", "in_list") is True)
        # Simpler: qa is not in "prod, dev" -> in_list = False, negated = True
        self.assertTrue(match("qa", "prod, dev", "in_list", negate=True))

    def test_hostname_pattern_match(self):
        # Typical hostname regex used in rules
        self.assertTrue(match("web-prod-01", r"web-prod-\d+", "regex"))
        self.assertFalse(match("db-prod-01", r"web-prod-\d+", "regex"))

    def test_tag_does_not_exist_semantic(self):
        # 'ignore' + negate is used by the rule engine to check "tag missing".
        # At the match() level it unconditionally returns False — the
        # "does not exist" decision is made one layer up (see rule.py).
        self.assertFalse(match("whatever", "", "ignore", negate=True))



class TestParseAge(unittest.TestCase):
    """The age a user types in a condition, in seconds."""

    def test_bare_number_counts_days(self):
        # The Jinja expression these conditions replace compared
        # (utcnow() - syncer_last_seen).days, so a plain 2 has to mean the
        # same two days here.
        self.assertEqual(parse_age("2"), 2 * 86400)

    def test_days(self):
        self.assertEqual(parse_age("2d"), 2 * 86400)

    def test_hours(self):
        self.assertEqual(parse_age("12h"), 12 * 3600)

    def test_minutes(self):
        self.assertEqual(parse_age("30m"), 30 * 60)

    def test_weeks(self):
        self.assertEqual(parse_age("1w"), 7 * 86400)

    def test_fraction_and_whitespace_and_case(self):
        self.assertEqual(parse_age(" 0.5D "), 12 * 3600)

    def test_nonsense_says_what_is_accepted(self):
        with self.assertRaises(ValueError) as ctx:
            parse_age("two days")
        self.assertIn("2d", str(ctx.exception))

    def test_empty_is_not_an_age(self):
        with self.assertRaises(ValueError):
            parse_age("")


class TestAgeInSeconds(unittest.TestCase):
    """How old the attribute's point in time is — or None if it is none."""

    def test_naive_datetime_is_read_as_utc(self):
        # Everything the syncer stores is naive UTC (Host.set_import_seen).
        stamp = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
        self.assertAlmostEqual(age_in_seconds(stamp), 3 * 3600, delta=60)

    def test_aware_datetime_is_converted(self):
        stamp = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(hours=3))
        self.assertAlmostEqual(age_in_seconds(stamp), 3 * 3600, delta=60)

    def test_iso_string_from_an_imported_attribute(self):
        stamp = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        self.assertAlmostEqual(age_in_seconds(stamp.isoformat()), 86400, delta=60)

    def test_plain_date_string(self):
        self.assertGreater(age_in_seconds("2000-01-01"), 0)

    def test_a_string_that_is_no_date_is_not_a_timestamp(self):
        self.assertIsNone(age_in_seconds("prod"))

    def test_none_is_not_a_timestamp(self):
        self.assertIsNone(age_in_seconds(None))


class TestAgeConditions(unittest.TestCase):
    """'Older Than' / 'Newer Than' hold an attribute against the clock."""

    def setUp(self):
        self.eight_days_ago = (datetime.datetime.utcnow()
                               - datetime.timedelta(days=8))
        self.an_hour_ago = (datetime.datetime.utcnow()
                            - datetime.timedelta(hours=1))

    def test_older_than_hit(self):
        # The case the customer asked for: not seen for more than two days.
        self.assertTrue(match(self.eight_days_ago, "2d", "older_than"))

    def test_older_than_miss(self):
        self.assertFalse(match(self.an_hour_ago, "2d", "older_than"))

    def test_newer_than_hit(self):
        # And back on again as soon as the host is seen.
        self.assertTrue(match(self.an_hour_ago, "2d", "newer_than"))

    def test_newer_than_miss(self):
        self.assertFalse(match(self.eight_days_ago, "2d", "newer_than"))

    def test_hours_and_minutes(self):
        self.assertTrue(match(self.an_hour_ago, "30m", "older_than"))
        self.assertFalse(match(self.an_hour_ago, "12h", "older_than"))

    def test_a_date_in_the_future_is_not_old(self):
        tomorrow = datetime.datetime.utcnow() + datetime.timedelta(days=1)
        self.assertFalse(match(tomorrow, "2d", "older_than"))
        self.assertTrue(match(tomorrow, "2d", "newer_than"))

    def test_an_attribute_that_is_no_timestamp_never_matches(self):
        # A host whose value is not a point in time falls through both
        # directions instead of raising and taking the export down.
        self.assertFalse(match("prod", "2d", "older_than"))
        self.assertFalse(match("prod", "2d", "newer_than"))
        self.assertFalse(match(None, "2d", "older_than"))
        self.assertFalse(match(None, "2d", "newer_than"))

    def test_negate_flips_the_result(self):
        self.assertFalse(match(self.eight_days_ago, "2d", "older_than",
                               negate=True))
        self.assertTrue(match(self.an_hour_ago, "2d", "older_than",
                              negate=True))

    def test_an_unusable_age_raises_match_exception(self):
        with self.assertRaises(MatchException) as ctx:
            match(self.eight_days_ago, "two days", "older_than")
        self.assertIn("older_than", str(ctx.exception))

    def test_check_condition_does_not_coerce_the_timestamp(self):
        # match() lowercases the operands of the string conditions; a
        # datetime must reach check_condition untouched.
        self.assertTrue(check_condition(self.eight_days_ago, "2d", "older_than"))


class TestRegexCache(unittest.TestCase):
    """_compiled_regex memoizes re.compile across calls with the same needle."""

    def test_same_needle_returns_same_pattern(self):
        pattern1 = _compiled_regex(r"web-\d+")
        pattern2 = _compiled_regex(r"web-\d+")

        # Same cached object — no recompile on the second call.
        self.assertIs(pattern1, pattern2)

    def test_cache_enforces_length_limit(self):
        overlong = "a" * (MAX_REGEX_LENGTH + 1)
        with self.assertRaises(re.error):
            _compiled_regex(overlong)


if __name__ == "__main__":
    unittest.main(verbosity=2)
