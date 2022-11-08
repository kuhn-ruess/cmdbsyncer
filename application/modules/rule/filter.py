#!/usr/bin/env python3
"""
Filter
"""
from application.modules.rule.rule import Rule

class Filter(Rule):# pylint: disable=too-few-public-methods
    """
    Filter Attributes
    """

    name = "Filter"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if attributes match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            if outcome['action'] == 'whitelist_attribute':
                attribute_name = outcome['attribute_name']
                if not attribute_name.endswith('*'):
                    if self.attriutes.get(attribute_name):
                        outcomes[attribute_name] = self.attriutes[attribute_name]
                else:
                    real_name = attribute_name[:-1]
                    for attribute in self.attriutes:
                        if attribute.startswith(real_name):
                            outcomes[attribute] = self.attributes[attribute]
            if outcome['action'] == 'ignore_hosts':
                outcomes['ignore_host'] = True
        return outcomes
