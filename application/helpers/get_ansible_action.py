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
        print(f"{rule}, {outcomes}")
        return outcomes
