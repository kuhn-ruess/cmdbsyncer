#!/usr/bin/env python3
"""
Get Host Params
"""

from application.models.rule import HostRule
from application.helpers.match import match


class GetHostParams(): # pylint: disable=too-few-public-methods
    """
    Class to get actions for rule
    """

    def __init__(self, target):
        """
        Prepare Rules
        """
        self.rules = [x.to_mongo() for x in HostRule.objects(enabled=True,
                                                             target=target).order_by('sort_field')]

    @staticmethod
    def _convert_params(params):
        """
        Convert Object to Dict
        """
        outcome = {}
        for param in params:
            if param['type'] == "ignore_host":
                outcome['ignore_host'] = True
            elif param['type'] == "add_custom_label":
                outcome.setdefault('custom_labels', {})
                print(param['value'])
                outcome['custom_labels'][param['name']] = param['value']
        return outcome


    def _check_rule_match(self, hostname):
        """
        Return Params if rule matches
        """

        # First rule Match
        outcomes = {'custom_labels': {}}
        for rule in self.rules:
            for condtion in rule['conditions']:
                cond_hostname = condtion['hostname']
                if match(hostname, cond_hostname, condtion['match'], condtion['match_negate']):
                    new_outcome = self._convert_params(rule['params'])
                    new_outcome.get('custom_labels', {}).update(outcomes['custom_labels'])
                    outcomes.update(new_outcome)
        return outcomes



    def get_params(self, hostname):
        """
        Return next Action for this Host
        """
        return self._check_rule_match(hostname)
