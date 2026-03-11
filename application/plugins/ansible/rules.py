#!/usr/bin/env python3
"""
Ansible Rules
"""
from application.modules.rule.rule import Rule
from application.helpers.get_account import get_account_variable
from application.helpers.syncer_jinja import render_jinja

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
            new_value  = render_jinja(attr_value, mode="nullify", **self.attributes).strip()
            outcomes[outcome['attribute_name']] = new_value
        return outcomes
