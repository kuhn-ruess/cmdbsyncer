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

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Add the new Attributes
        """
        for outcome in rule_outcomes:
            outcomes[outcome['attribute_name']] = outcome['attribute_value']
        return outcomes



    def _check_rule_match(self, hostname):
        """
        Return dict with new attributes
        """

        # First rule Match
        outcomes = {'custom_attributes': {}}
        for rule in self.rules:
            for condtion in rule['conditions']:
                cond_hostname = condtion['hostname']
                if match(hostname, cond_hostname, condtion['match'], condtion['match_negate']):
                    new_outcome = self._convert_params(rule['params'])
                    # Merge old Attributes to the new ones
                    outcomes.update(new_outcome)
        return outcomes

