#!/usr/bin/env python3
"""
Get Action
"""

from application.models.netbox_rule import NetboxCustomVariables
from application.helpers.action import Action

class GetNetboxsRules(Action):
    """
    Get Defined Rules
    """
    def __init__(self, debug=False):
        """
        Prepare Rules
        """
        self.rules = \
            [x.to_mongo() for x in \
                 NetboxCustomVariables.objects(enabled=True).order_by('sort_field')]
        self.debug = debug

    def add_outcomes(self, rule, outcomes):
        for outcome in rule['outcome']:
            if outcome['type'] == "ignore_host":
                outcomes['ignore_host'] = True
            else:
                value = outcome['value']
                outcomes[outcome['type'].replace('nb_','')] = value
        return outcomes
