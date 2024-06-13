#!/usr/bin/env python3
"""
Handle Rule Matching
"""
# pylint: disable=import-error
# pylint: disable=logging-fstring-interpolation
import re
from rich.console import Console
from rich.table import Table
from rich import box

from application import logger, app

from application.modules.rule.match import match

class Rule(): # pylint: disable=too-few-public-methods
    """
    Base Rule Class
    """
    debug = False
    debug_lines = []
    rules = []
    name = ""
    attributes = {}
    hostname = False
    db_host = False
    cache_name = False


    def __init__(self):
        self.debug_lines = []

    @staticmethod
    def replace(input_raw, exceptions=None, regex=None):
        """
        Replace all given inputs
        """
        if regex:
            result = re.sub(regex, '', input_raw.strip())
            return result
        if not exceptions:
            exceptions = []
        input_str = str(input_raw)
        for needle, replacer in app.config['REPLACERS']:
            if needle in exceptions:
                continue
            input_str = input_str.replace(needle, replacer)
        return input_str.strip()

    def _check_attribute_match(self, condition):
        """
        Check if on of the given attributes match the rule
        """
        needed_tag = condition['tag']
        tag_match = condition['tag_match']
        tag_match_negate = condition['tag_match_negate']

        needed_value = condition['value']
        value_match = condition['value_match']
        value_match_negate = condition['value_match_negate']


        if tag_match == 'ignore' and tag_match_negate:
            # This Case Checks that Tag NOT Exists
            if needed_tag not in self.attributes.keys():
                return True
            return False
        # Wee need to find out if tag AND tag value match
        for tag, value in self.attributes.items():
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

    def check_rules(self, hostname): #pylint: disable=too-many-branches
        """
        Handle Rule Match logic
        """
        #pylint: disable=too-many-branches

        rule_descriptions = {
            'any' : "ANY can match",
            'all' : "ALL must match",
            'anyway': "ALWAYS match"
        }
        if self.debug:
            title = f"Debug '{self.name}' Rules for {hostname}"

            table = Table(title=title, box=box.ASCII_DOUBLE_HEAD,\
                        header_style="bold blue", title_style="yellow", \
                        title_justify="left", width=90)
            table.add_column("Hit")
            table.add_column("Description")
            table.add_column("Rule Name")
            table.add_column("Rule ID")
            table.add_column("Last Match")

        outcomes = {}
        for rule in self.rules:
            rule = rule.to_mongo()
            rule_hit = False
            if rule['condition_typ'] == 'any':
                for condtion in rule['conditions']:
                    local_hit = False
                    if condtion['match_type'] == 'tag':
                        local_hit = self._check_attribute_match(condtion)
                    else:
                        local_hit = self._check_hostname_match(condtion, hostname)
                    if local_hit:
                        rule_hit = True
            elif rule['condition_typ'] == 'all':
                negativ_match = False
                for condtion in rule['conditions']:
                    if condtion['match_type'] == 'tag':
                        if not self._check_attribute_match(condtion):
                            negativ_match = True
                    else:
                        if not self._check_hostname_match(condtion, hostname):
                            negativ_match = True
                if not negativ_match:
                    rule_hit = True
            elif rule['condition_typ'] == 'anyway':
                rule_hit = True

            if self.debug:
                debug_data = {
                    "group": self.name,
                    "hit": rule_hit,
                    "condition_type": rule_descriptions[rule['condition_typ']],
                    "name": rule['name'],
                    "id": str(rule['_id']),
                    "last_match": str(rule['last_match'])
                }
                self.debug_lines.append(debug_data)
                table.add_row(str(rule_hit), rule_descriptions[rule['condition_typ']],\
                              rule['name'][:30], str(rule['_id']), str(rule['last_match']))
            if rule_hit:
                outcomes = self.add_outcomes([dict(x) for x in rule['outcomes']], outcomes)
                # If rule has matched, and option is set, we are done
                if rule['last_match']:
                    break
        if self.debug:
            console = Console()
            console.print(table)
            print()
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


    def get_outcomes(self, db_host, attributes):
        """
        Handle Return of outcomes.
        """
        cache = self.__class__.__qualname__
        if self.cache_name:
            cache = self.cache_name
        if cache in db_host.cache:
            logger.debug(f"Using Rule Cache Cache for {db_host.hostname}")
            return db_host.cache[cache]

        self.attributes = attributes
        self.hostname = db_host.hostname
        self.db_host = db_host
        rules = self.check_rule_match(db_host)
        db_host.cache[cache] = rules
        db_host.save()
        return rules
