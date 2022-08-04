#!/usr/bin/env python3
"""
Get Action
"""

from application.models.ansible_rule import AnsibleRule
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
                outcomes['vars'][outcome['param']] = outcome['value']
        return outcomes
