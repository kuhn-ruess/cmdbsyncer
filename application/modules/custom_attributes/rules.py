#!/usr/bin/env python3
# pylint: disable=no-member
"""
Custom Attributes for Host
"""
from application.modules.rule.rule import Rule



class CustomAttributeRule(Rule): # pylint: disable=too-few-public-methods
    """
    Return Custom Attributes for given Host
    """

    name = "Custom Attributes"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Add the new Attributes
        """
        for outcome in rule_outcomes:
            if not outcome:
                continue
            attribute_value = outcome['attribute_value']
            if attribute_value == 'True':
                attribute_value = True
            elif attribute_value == 'False':
                attribute_value = False
            outcomes[outcome['attribute_name']] = attribute_value
        return outcomes
