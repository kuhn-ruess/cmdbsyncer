#!/usr/bin/env python3
"""
Get Action
"""

from application.models.ansible_rule import AnsibleRule, AnsibleCustomVariables
from application.helpers.action import Action

class GetAnsibleAction(Action): # pylint: disable=too-few-public-methods
    """
    Class to get actions for rule
    """

    def __init__(self, debug=False):
        """
        Prepare Rules
        """
        self.rules = \
            [x.to_mongo() for x in \
                 AnsibleRule.objects(enabled=True).order_by('sort_field')]
        self.debug = debug

    def add_outcomes(self, rule, outcomes):
        for outcome in rule['outcome']:
            if outcome['type'] == "ignore":
                outcomes['ignore'] = True
            elif outcome['type'] == 'var':
                outcomes.setdefault('vars', {})
                value = outcome['value']
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
                outcomes['vars'][outcome['param']] = value
        return outcomes


class GetAnsibleCustomVars(Action):
    """
    Get Defined Custom Variables
    """
    def __init__(self, debug=False):
        """
        Prepare Rules
        """
        self.rules = \
            [x.to_mongo() for x in \
                 AnsibleCustomVariables.objects(enabled=True).order_by('sort_field')]
        self.debug = debug

    def add_outcomes(self, rule, outcomes):
        for outcome in rule['outcome']:
            if outcome['type'] == 'var':
                value = outcome['value']
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
                outcomes[outcome['param']] = value
        return outcomes
