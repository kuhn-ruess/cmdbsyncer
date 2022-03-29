#!/usr/bin/env python3
"""
Get Label
"""

from application.models.rule import LabelRule


class GetLabel():# pylint: disable=too-few-public-methods
    """
    Filter Labels
    """

    def __init__(self):
        """
        Prepare Rules
        """
        self.rules = [x.to_mongo() for x in LabelRule.objects(enabled=True).order_by('sort_field')]

    @staticmethod
    def _check_label_match(condition, label):
        """
        Check if on of the given labels match the rule
        """
        needed_value = condition['value']
        match_type = condition['type']

        label = label.lower()
        if match_type == 'equal':
            if label == needed_value.lower():
                return True
        elif match_type == 'not_equal':
            if label != needed_value.lower():
                return True
        elif match_type == "in":
            if needed_value.lower() in label:
                return True
        elif match_type == 'swith':
            if label.startswit(needed_value):
                return True
        elif match_type == 'ewith':
            if label.endswith(needed_value):
                return True
        return False


    def filter_labels(self, labels):
        """
        Filter if labels match to a rule
        """
        matches = {}
        # pylint: disable=too-many-nested-blocks
        for label, value in labels.items():
            for rule in self.rules:
                hit = False
                for condition in rule['conditions']:
                    if self._check_label_match(condition, label):
                        hit = True
                        outcome = rule['outcome']
                        if not 'remove' in outcome and 'add' in outcome:
                            if 'strip' in outcome:
                                label = label.strip()
                            if 'lower' in outcome:
                                label = label.lower()
                            if 'replace' in outcome:
                                label = label.replace(' ', '_')
                            matches[label] = value
                        break
                # Break out the rules if condition had a hit
                # we go on with next label then
                if hit:
                    break
        return matches
