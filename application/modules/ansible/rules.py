#!/usr/bin/env python3
"""
Ansible Rules
"""
from application.modules.rule.rule import Rule

class AnsibleVariableRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom Variables for Ansible
    """

    name = "Ansible -> Custom Variables"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if Attributes match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            outcomes[outcome['attribute_name']] = outcome['attribute_value']
        return outcomes
