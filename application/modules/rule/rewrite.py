#!/usr/bin/env python3
"""
Rewrite
"""
from application.modules.rule.rule import Rule

class Rewrite(Rule):# pylint: disable=too-few-public-methods
    """
    Rewrite Attributes
    """

    name = "Rewrite"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Rewrite matching Attribute
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            attribute_name = outcome['old_attribute_name']
            new_attribute_name = outcome['new_attribute_name']
            if self.attributes.get(attribute_name):
                outcomes[f'add_{new_attribute_name}'] = self.attributes[attribute_name]
                outcomes[f'del_{attribute_name}'] = True
        return outcomes
