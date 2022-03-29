#!/usr/bin/env python3
"""
Get Host Params
"""

from application.models.rule import HostRule


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
            if param['type'] == "ignore_hosts":
                outcome['ignore_hosts'] = True
            elif param['type'] == "add_custom_label":
                outcome.setdefault('custom_labels', {})
                outcome['custom_labels'][param['name']] = param['value']
        return outcome


    def _check_rule_match(self, hostname):
        """
        Return Params if rule matches
        """

        # First rule Match
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
                elif condtion['match'] == 'swith':
                    if hostname.startswith(cond_hostname):
                        return self._convert_params(rule['params'])
                elif condtion['match'] == 'ewith':
                    if hostname.endswith(cond_hostname):
                        return self._convert_params(rule['params'])
        return {}



    def get_params(self, hostname):
        """
        Return next Action for this Host
        """
        return self._check_rule_match(hostname)
