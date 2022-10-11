#!/usr/bin/env python3
"""
Get Action
"""

from application.models.ansible_rule import AnsibleCustomVariables
from application.helpers.action import Action

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
            if outcome['type'] == "ignore":
                outcomes['ignore'] = True
            if outcome['type'] == 'var':
                value = outcome['value']
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
                outcomes[outcome['param']] = value
        return outcomes
