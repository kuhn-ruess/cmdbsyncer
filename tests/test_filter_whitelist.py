"""
The whitelist of the Filter rules.
"""
# pylint: disable=missing-function-docstring
import unittest

from application.modules.rule.filter import Filter


def _outcomes(attributes, attribute_name):
    rule = Filter.__new__(Filter)
    rule.attributes = attributes
    outcome = {'action': 'whitelist_attribute', 'attribute_name': attribute_name}
    return rule.add_outcomes(None, [outcome], {})


class WhitelistTest(unittest.TestCase):
    """An exact name"""

    def test_zero_and_false_are_values(self):
        self.assertEqual(_outcomes({'a': 0}, 'a'), {'a': 0})
        self.assertEqual(_outcomes({'a': False}, 'a'), {'a': False})
        self.assertEqual(_outcomes({'a': 'x'}, 'a'), {'a': 'x'})

    def test_no_value_stays_out(self):
        self.assertEqual(_outcomes({'a': ''}, 'a'), {})
        self.assertEqual(_outcomes({'a': None}, 'a'), {})
        self.assertEqual(_outcomes({}, 'a'), {})
