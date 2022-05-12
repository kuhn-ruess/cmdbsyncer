#!/usr/bin/env python3
"""
Get Action
"""

from application.models.rule import ActionRule
from application.helpers.match import match
from application.helpers.debug import debug

class GetAction(): # pylint: disable=too-few-public-methods
    """
    Class to get actions for rule
    """

    def __init__(self, debug=False):
        """
        Prepare Rules
        """
        self.rules = [x.to_mongo() for x in ActionRule.objects(enabled=True).order_by('sort_field')]
        self.debug = debug

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

    @staticmethod
    def _check_hostname_match(condition, hostname):
        """
        Check if Condition Matchs to Hostname
        """
        needed = condition['hostname'].lower()
        host_match = condition['hostname_match'].lower()
        negate = condition['hostname_match_negate']

        if match(hostname.lower(), needed, host_match, negate):
            return True
        return False


    def _check_rule_match(self, hostname, labels):
        """
        Return True if rule matches
        """
        #pylint: disable=too-many-branches
        outcomes = {}
        # In this loop we collect all possible rule outcomes which lead to the
        # actions which happens to the host
        debug(self.debug, f"Debug Rules for {hostname}")
        for rule in self.rules:
            rule_hit = False
            if rule['condition_typ'] == 'any':
                for condtion in rule['conditions']:
                    if condtion['match_type'] == 'tag':
                        rule_hit = self._check_label_match(condtion, labels)
                    else:
                        rule_hit = self._check_hostname_match(condtion, hostname)
            elif rule['condition_typ'] == 'all':
                negativ_match = False
                for condtion in rule['conditions']:
                    if condtion['match_type'] == 'tag':
                        if not self._check_label_match(condtion, labels):
                            negativ_match = True
                    else:
                        if not self._check_hostname_match(condtion, hostname):
                            negativ_match = True
                if not negativ_match:
                    rule_hit = True
            elif rule['condition_typ'] == 'anyway':
                rule_hit = True

            # Rule matches, get outcome
            if rule_hit:
                debug(self.debug, f"-- Rule id {rule['_id']} hit")
                for outcome in rule['outcome']:
                    # We add only the outcome of the
                    # first matching rule type
                    if outcome['type'] not in outcomes:
                        debug(self.debug, f"--- Added Outcome {outcome['type']} = {outcome['param']}")
                        outcomes[outcome['type']] = outcome['param']
                # If rule has matched, and option is set, we are done
                if rule['last_match']:
                    debug(self.debug, f"--- Rule id {rule['_id']} was last_match")
                    return outcomes

            # Handle Special Options for Rules
            if 'value_as_folder' in outcomes:
                debug(self.debug, "-- value as folder matched, overwrite move_folder if tag is found")
                search_tag = outcomes['value_as_folder']
                for tag, value in labels.items():
                    if search_tag == value:
                        debug(self.debug, f"--- Found tag, overwrite folder with: {tag}")
                        outcomes['move_folder'] = tag

            if 'tag_as_folder' in outcomes:
                debug(self.debug, "-- tag as folder matched, overwrite move_folder if value is found")
                search_value = outcomes['tag_as_folder']
                for tag, value in labels.items():
                    if search_value == tag:
                        debug(self.debug, f"--- Found value, overwrite folder with: {value}")
                        outcomes['move_folder'] = value

        return outcomes


    def get_action(self, hostname, labels):
        """
        Return next Action for this Host
        """
        return self._check_rule_match(hostname, labels)
