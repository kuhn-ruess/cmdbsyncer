"""
Unit tests for the rule matching engine.

Covers:
  - application.modules.rule.match.check_condition (pure condition dispatch)
  - application.modules.rule.match.match (negation, type coercion, errors)
  - application.modules.rule.match.make_bool
"""
# pylint: disable=missing-function-docstring
import unittest

from application.modules.rule.match import (
    check_condition,
    match,
    make_bool,
    MatchException,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
