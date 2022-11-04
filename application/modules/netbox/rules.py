#!/usr/bin/env python3
"""
Netbox Rules
"""
from application.modules.rule.rule import Rule

class NetboxVariableRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom Variables for Ansible
    """

    name = "Netbox -> Custom Attributes"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            outcomes[outcome['action']] = outcome['param']
        return outcomes
