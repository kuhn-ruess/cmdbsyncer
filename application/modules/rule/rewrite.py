#!/usr/bin/env python3
"""
Rewrite
"""
from application.modules.rule.rule import Rule

class Rewrite(Rule):# pylint: disable=too-few-public-methods
    """
    Rewrite Labels
    """

    name = "Rewrite"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Rewrite matching label
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            label_name = outcome['old_label_name']
            new_label_name = outcome['new_label_name']
            if self.labels.get(label_name):
                outcomes[f'add_{new_label_name}'] = self.labels[label_name]
                outcomes[f'del_{label_name}'] = True
        return outcomes
