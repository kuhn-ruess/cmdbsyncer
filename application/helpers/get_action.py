#!/usr/bin/env python3
"""
Get Action
"""

from application.models.rule import ActionRule
from application.helpers.match import match

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
        tag_match_negate = condition['tag_match_negate']

        needed_value = condition['value']
        value_match = condition['value_match']
        value_match_negate = condition['value_match_negate']

        # Wee need to find out if tag AND tag value match

        for tag, value in labels.items():
            # Check if Tag matchs
            if match(tag, needed_tag, tag_match, tag_match_negate):
                # Tag Match, see if Value Match
                if match(value.lower(), needed_value.lower(), value_match, value_match_negate):
                    return True
        return False


    def _check_rule_match(self, labels):
        """
        Return True if rule matches
        """
        outcomes = {}
        for rule in self.rules:
            rule_hit = False
            if rule['condition_typ'] == 'any':
                for condtion in rule['conditions']:
                    rule_hit = self._check_label_match(condtion, labels)
            elif rule['condition_typ'] == 'all':
                negativ_match = False
                for condtion in rule['conditions']:
                    if not self._check_label_match(condtion, labels):
                        negativ_match = True
                if not negativ_match:
                    rule_hit = True
            elif rule['condition_typ'] == 'anyway':
                rule_hit = True

            # Rule matches, get outcome
            if rule_hit:
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
