#!/usr/bin/env python3
"""
Get Action
"""

from application.helpers.match import match
from application.helpers.debug import debug as print_debug
from application.helpers.debug import ColorCodes

class Action(): # pylint: disable=too-few-public-methods
    """
    Class to get actions for rule
    """
    debug = False
    rules = []

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

    def check_rules(self, hostname, labels):
        """
        Handle Rule Match logic
        """
        #pylint: disable=too-many-branches
        print_debug(self.debug, "Debug Rules for "\
                                f"{ColorCodes.UNDERLINE}{hostname}{ColorCodes.ENDC}")
        outcomes = {}
        for rule in self.rules:
            rule_hit = False
            if rule['condition_typ'] == 'any':
                print_debug(self.debug,
                            "- Rule Type: ANY can match "\
                           f"(RuleID: {ColorCodes.OKBLUE}{rule['_id']}{ColorCodes.ENDC})")
                for condtion in rule['conditions']:
                    local_hit = False
                    if condtion['match_type'] == 'tag':
                        local_hit = self._check_label_match(condtion, labels)
                    else:
                        local_hit = self._check_hostname_match(condtion, hostname)
                    if local_hit:
                        rule_hit = True
            elif rule['condition_typ'] == 'all':
                print_debug(self.debug,
                            "- Rule Type: ALL must match "\
                            f"(RuleID: {ColorCodes.OKBLUE}{rule['_id']}{ColorCodes.ENDC})")
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
                print_debug(self.debug,
                            "- Rule Typ: Match without condition' "\
                            f"(RuleID: {ColorCodes.OKBLUE}{rule['_id']}{ColorCodes.ENDC})")
                rule_hit = True
            if rule_hit:
                print_debug(self.debug,
                            f"-- {ColorCodes.OKCYAN}Rule Hit{ColorCodes.ENDC}")
                outcomes = self.add_outcomes(rule, outcomes)

                # If rule has matched, and option is set, we are done
                if rule['last_match']:
                    print_debug(self.debug, f"--- {ColorCodes.FAIL}Rule id "\
                                             f"{rule['_id']} was last_match{ColorCodes.ENDC}")
                    break

        return outcomes

    def add_outcomes(self, rule, outcomes):
        """
        Please implement
        """
        raise NotImplementedError


    def check_rule_match(self, db_host, labels):
        """
        Handle Return of outcomes.
        """
        return self.check_rules(db_host.hostname, labels)

    def get_action(self, db_host, labels):
        """
        Return next Action for this Host
        """
        return self.check_rule_match(db_host, labels)
