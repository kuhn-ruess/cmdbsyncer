#!/usr/bin/env python3
"""
Idoit Rules
"""
from application.modules.rule.rule import Rule

class IdoitVariableRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom Variables for Idoit
    """

    name = "Idoit -> Custom Attributes"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            outcomes[outcome['action']] = outcome['param']
        return outcomes
