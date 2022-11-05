#!/usr/bin/env python3
"""
Handle Rule Matching
"""

from application.modules.rule.match import match
from application.modules.debug import debug as print_debug
from application.modules.debug import ColorCodes as CC

class Rule(): # pylint: disable=too-few-public-methods
    """
    Base Rule Class
    """
    debug = False
    rules = []
    name = ""

    def _check_label_match(self, condition):
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
        for tag, value in self.labels.items():
            # Check if Tag matchs
            if match(tag, needed_tag, tag_match, tag_match_negate):
                # Tag Match, see if Value Match
                if match(value, needed_value, value_match, value_match_negate):
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

    def check_rules(self, hostname):
        """
        Handle Rule Match logic
        """

        rule_descriptions = {
            'any' : "ANY can match",
            'all' : "ALL must match",
            'anyway': "ALLWAYS match"
        }
        #pylint: disable=too-many-branches
        print_debug(self.debug, f"Debug '{self.name}' Rules for "\
                                f"{CC.UNDERLINE}{hostname}{CC.ENDC}")
        outcomes = {}
        for rule in self.rules:
            rule = rule.to_mongo()
            rule_hit = False
            if rule['condition_typ'] == 'any':
                for condtion in rule['conditions']:
                    local_hit = False
                    if condtion['match_type'] == 'tag':
                        local_hit = self._check_label_match(condtion)
                    else:
                        local_hit = self._check_hostname_match(condtion, hostname)
                    if local_hit:
                        rule_hit = True
            elif rule['condition_typ'] == 'all':
                negativ_match = False
                for condtion in rule['conditions']:
                    if condtion['match_type'] == 'tag':
                        if not self._check_label_match(condtion):
                            negativ_match = True
                    else:
                        if not self._check_hostname_match(condtion, hostname):
                            negativ_match = True
                if not negativ_match:
                    rule_hit = True
            elif rule['condition_typ'] == 'anyway':
                rule_hit = True

            hit_text = ""
            if rule_hit:
                hit_text = f" {CC.OKCYAN}HIT{CC.ENDC}"

            print_debug(self.debug,
                           f"{CC.OKBLUE}*{CC.ENDC}{hit_text} {rule_descriptions[rule['condition_typ']]} "\
                           f"(RuleID: {CC.OKBLUE}{rule['name'][:20]} ({rule['_id']}){CC.ENDC})")
            if rule_hit:
                outcomes = self.add_outcomes([dict(x) for x in rule['outcomes']], outcomes)

                # If rule has matched, and option is set, we are done
                if rule['last_match']:
                    print_debug(self.debug, f"{CC.OKBLUE}**{CC.ENDC} {CC.FAIL}Rule id "\
                                             f"{rule['_id']} was last_match{CC.ENDC}")
                    break

        print_debug(self.debug,
                    f"{CC.OKBLUE}--------------------------------------------------------------------{CC.ENDC}")
        return outcomes

    def add_outcomes(self, rule, outcomes):
        """
        Please implement
        """
        raise NotImplementedError

    def check_rule_match(self, db_host):
        """
        Handle Return of outcomes.
        This Function in needed in case a plugin needs to overwrite
        content in the class. In this case the plugin like checkmk rule overwrite this function
        """
        return self.check_rules(db_host.hostname)


    def get_outcomes(self, db_host, labels):
        """
        Handle Return of outcomes.
        """
        self.labels = labels
        return self.check_rule_match(db_host)
