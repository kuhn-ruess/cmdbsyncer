#!/usr/bin/env python3
"""
Rewrite
"""
import re
from application.modules.rule.rule import Rule

class Rewrite(Rule):# pylint: disable=too-few-public-methods
    """
    Rewrite Attributes
    """

    name = "Rewrite"
    rewrite_cache = {}

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Rewrite matching Attribute
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            attribute_name = outcome['old_attribute_name']
            new_attribute_name = outcome['new_attribute_name']
            if attribute_name.startswith('~'):
                pattern = attribute_name[1:]
                # Can may be simplified since i heared Python
                # Handles the cache anyway
                if not self.rewrite_cache.get(pattern):
                    self.rewrite_cache[pattern] = re.compile(pattern)
                for key, value in self.attributes.items():
                    if self.rewrite_cache[pattern].match(key):
                        outcomes[f'add_{new_attribute_name}'] = value
                        outcomes[f'del_{key}'] = True
            else:
                if self.attributes.get(attribute_name):
                    outcomes[f'add_{new_attribute_name}'] = self.attributes[attribute_name]
                    outcomes[f'del_{attribute_name}'] = True
        return outcomes
