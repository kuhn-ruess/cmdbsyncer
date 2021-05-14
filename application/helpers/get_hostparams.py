#!/usr/bin/env python3
"""
Get Host Params
"""

from application.models.rule import HostRule


class GetHostParams(): # pylint: disable=too-few-public-methods
    """
    Class to get actions for rule
    """

    def __init__(self):
        """
        Prepare Rules
        """
        self.rules = [x.to_mongo() for x in HostRule.objects(enabled=True)]

    @staticmethod
    def _convert_params(params):
        """
        Convert Object to Dict
        """
        outcome = {}
        for param in params:
            outcome[param['name']] = {
                'bool': param['trigger'],
                'value': param['value'],
            }
        return outcome


    def _check_rule_match(self, hostname):
        """
        Return Params if rule matches
        """
        for rule in self.rules:
            for condtion in rule['conditions']:
                cond_hostname = condtion['hostname']
                if condtion['match'] == 'equal':
                    if cond_hostname == hostname:
                        return self._convert_params(rule['params'])
                elif condtion['match'] == 'not_equal':
                    if cond_hostname != hostname:
                        return self._convert_params(rule['params'])
                elif condtion['match'] == 'in':
                    if cond_hostname in hostname:
                        return self._convert_params(rule['params'])
        return {}



    def get_params(self, hostname):
        """
        Return next Action for this Host
        """
        return self._check_rule_match(hostname)
