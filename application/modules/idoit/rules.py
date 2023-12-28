#!/usr/bin/env python3
"""
i-doit Rules
"""
from application.modules.rule.rule import Rule

class IdoitVariableRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom variables for i-doit
    """

    name = "i-doit -> Custom attributes"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """

        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            outcomes[outcome['action']] = outcome['param']
        return outcomes
