#!/usr/bin/env python3
# pylint: disable=no-member
"""
Custom Labels for Host
"""

from application.modules.rule.models import CustomLabelRule
from application.modules.rule.match import match


class CustomLabels(): # pylint: disable=too-few-public-methods
    """
    Return Custom Labels for given Host
    """

    def __init__(self):
        """
        Prepare Rules
        """
        self.rules = [x.to_mongo() for x in CustomLabelRule.objects(enabled=True,
                                                                 ).order_by('sort_field')]

    @staticmethod
    def _convert_params(params):
        """
        Convert Object to Dict
        """
        outcome = {}
        for param in params:
            outcome[param['name']] = param['value']
        return outcome


    def _check_rule_match(self, hostname):
        """
        Return dict with new labels
        """

        # First rule Match
        outcomes = {'custom_labels': {}}
        for rule in self.rules:
            for condtion in rule['conditions']:
                cond_hostname = condtion['hostname']
                if match(hostname, cond_hostname, condtion['match'], condtion['match_negate']):
                    new_outcome = self._convert_params(rule['params'])
                    # Merge old labels to the new ones
                    outcomes.update(new_outcome)
        return outcomes


    def get_labels(self, hostname):
        """
        Return next Action for this Host
        """
        return self._check_rule_match(hostname)
