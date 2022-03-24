#!/usr/bin/env python3
"""
Get Action
"""

from application.models.rule import ActionRule


class GetAction(): # pylint: disable=too-few-public-methods
    """
    Class to get actions for rule
    """

    def __init__(self):
        """
        Prepare Rules
        """
        self.rules = [x.to_mongo() for x in ActionRule.objects(enabled=True).order_by('sort_field')]

    @staticmethod
    def _check_label_match(condition, labels):
        """
        Check if on of the given labels match the rule
        """
        needed_tag = condition['tag']
        tag_match = condition['tag_match']
        needed_value = condition['value']
        value_match = condition['value_match']

        for tag, value in labels.items():
            if tag_match == 'swith':
                if not tag.startswith(needed_tag):
                    continue
            elif tag_match == 'ewith':
                if not tag.endswith(needed_tag):
                    continue
            else:
                if tag != needed_tag:
                    continue
            if value_match == 'equal':
                if value == needed_value:
                    return True
            elif value_match == 'not_equal':
                if value != needed_value:
                    return True
            elif value_match == "in":
                if needed_value in value:
                    return True
        return False


    def _check_rule_match(self, labels):
        """
        Return True if rule matches
        """
        outcomes = {}
        for rule in self.rules:
            match = False
            if rule['condition_typ'] == 'any':
                for condtion in rule['conditions']:
                    match = self._check_label_match(condtion, labels)
            elif rule['condition_typ'] == 'all':
                negativ_match = False
                for condtion in rule['conditions']:
                    if not self._check_label_match(condtion, labels):
                        negativ_match = True
                if not negativ_match:
                    match = True
            elif rule['condition_typ'] == 'anyway':
                match = True

            # Rule matches, get outcome
            if match:
                for outcome in rule['outcome']:
                    # We add only the outcome of the
                    # first matching rule type
                    if outcome['type'] not in outcomes:
                        outcomes[outcome['type']] = outcome['param']
                # If rule has matched, and option is set, we are done
                if rule['last_match']:
                    return outcomes

        return outcomes


    def get_action(self, labels):
        """
        Return next Action for this Host
        """
        return self._check_rule_match(labels)
