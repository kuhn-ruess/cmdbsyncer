#!/usr/bin/env python3
"""
Ansible Rules
"""
from application.modules.rule.rule import Rule
from application.helpers.get_account import get_account_variable

class AnsibleVariableRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom Variables for Ansible
    """

    name = "Ansible -> Custom Variables"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Filter if Attributes match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            attr_value = outcome['attribute_value']
            if attr_value.startswith('{{ACCOUNT:'):
                try:
                    attr_value = get_account_variable(attr_value)
                except ValueError:
                    pass
            outcomes[outcome['attribute_name']] = attr_value
        return outcomes
