#!/usr/bin/env python3
"""
Filter
"""
from application.modules.rule.rule import Rule

class Filter(Rule):# pylint: disable=too-few-public-methods
    """
    Filter Labels/ Hosts
    """

    name = "Filter"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            if outcome['action'] == 'whitelist_attribute':
                label_name = outcome['attribute_name']
                if not label_name.endswith('*'):
                    if self.labels.get(label_name):
                        outcomes[label_name] = self.labels[label_name]
                else:
                    real_name = label_name[:-1]
                    for label in self.labels:
                        if label.startswith(real_name):
                            outcomes[label] = self.labels[label]
            if outcome['action'] == 'ignore_hosts':
                outcomes['ignore_host'] = True
        return outcomes
