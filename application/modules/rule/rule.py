#!/usr/bin/env python3
"""
Handle Rule Matching
"""
# pylint: disable=import-error
# pylint: disable=logging-fstring-interpolation
import ast
import re
from rich.console import Console
from rich.table import Table
from rich import box

from application import logger, app
from application.modules.rule.match import match
from application.helpers.syncer_jinja import render_jinja

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
        """
        Init
        """
        # Reset Debug Lines in Order for each child
        # of this class having a new log
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


        needed_value = render_jinja(needed_value, **self.attributes)

        if tag_match == 'ignore' and tag_match_negate:
            # This Case Checks that Tag NOT Exists
            if needed_tag not in self.attributes.keys():
                return True
            return False
        # Wee need to find out if tag AND tag value match
        for tag, value in self.attributes.items():
            # Handle special dict key custom_fields
            if "custom_fields" == tag and isinstance(value, dict):
                for name, content in value.items():
                    if f'custom_fields["{name}"]' == needed_tag:
                        # User writting custom_fields["name"]
                        tag = f'custom_fields["{name}"]'
                        value = content
                    elif f"custom_fields['{name}']" == needed_tag:
                        # User writting custom_fields['name']
                        tag = f"custom_fields['{name}']"
                        value = content

            # Check if Tag matchs
            if app.config['ADVANCED_RULE_DEBUG']:
                logger.debug(f"Check Tag: {tag} vs needed: {needed_tag} "\
                             f"for {tag_match}, Negate: {tag_match_negate}")
            # If the Tag with the Name matches, we cann check if the value is allright
            if match(tag, needed_tag, tag_match, tag_match_negate):
                if app.config['ADVANCED_RULE_DEBUG']:
                    logger.debug('--> HIT')
                    logger.debug(f"Check Attr Value: {repr(value)} "\
                                 " vs needed: {repr(needed_value)} "\
                                 f"for {value_match}, Negate: {value_match_negate}")
                # Tag had Match, now see if Value Matches too
                if match(value, needed_value, value_match, value_match_negate):
                    if app.config['ADVANCED_RULE_DEBUG']:
                        logger.debug('--> HIT')
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


    def handle_match(self, condition, hostname):
        """
        Check if a Host or Attribute Condition has a match
        """
        if condition['match_type'] == 'tag':
            return self._check_attribute_match(condition)
        return self._check_hostname_match(condition, hostname)

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
            if app.config['ADVANCED_RULE_DEBUG']:
                logger.debug('##########################')
                logger.debug(f'Check Rule: {rule.name}')
                logger.debug('##########################')
            rule = rule.to_mongo()
            rule_hit = False

            if rule['condition_typ'] == 'any':
                for condition in rule['conditions']:
                    if self.handle_match(condition, hostname):
                        rule_hit = True
                        break # We have a hit, no need to check more

            elif rule['condition_typ'] == 'all':
                rule_hit = True
                for condition in rule['conditions']:
                    if not self.handle_match(condition, hostname):
                        rule_hit = False
                        break # One was no hit, no need for loop

            elif rule['condition_typ'] == 'anyway':
                rule_hit = True


            if self.debug:
                debug_data = {
                    "group": self.name,
                    "hit": rule_hit,
                    "condition_type": rule_descriptions[rule['condition_typ']],
                    "name": rule['name'],
                    "id": str(rule['_id']),
                    "last_match": str(rule['last_match']),
                }
                self.debug_lines.append(debug_data)
                table.add_row(str(rule_hit), rule_descriptions[rule['condition_typ']],\
                              rule['name'][:30], str(rule['_id']), str(rule['last_match']))
            if rule_hit:
                outcomes = self.add_outcomes(rule, [dict(x) for x in rule['outcomes']], outcomes)
                # If rule has matched, and option is set, we are done
                if rule['last_match']:
                    break
        if self.debug:
            console = Console()
            console.print(table)
            print()
        return outcomes

    def handle_fields(self, field_name, field_value):
        """
        Default, overwrite if needed
        Rewrites Attributes if needed in get_multilist_outcomes mode
        """
        #pylint: disable= unused-argument
        return field_value

    def get_multilist_outcomes(self, rule_outcomes, ignore_field):
        """
        Central Function which helps 
        with list based outcomes to prevent the need of to many rules
        """
        outcome_selection = []

        defaults_for_list = {}
        defaults_by_id = {}
        #hostname = self.db_host.hostname

        ignore_list = []

        for outcome in rule_outcomes:
            action_param = outcome['param']
            action = outcome['action']
            if outcome['list_variable_name']:
                varname = outcome['list_variable_name']

                if input_list := self.attributes.get(varname):
                    if isinstance(input_list, str):
                        input_list = ast.literal_eval(input_list.replace('\n',''))
                    for idx, data in enumerate(input_list):
                        defaults_by_id.setdefault(idx, {})

                        if isinstance(action_param, list):
                            new_list = []
                            for entry in action_param:
                                new_value  = render_jinja(entry, mode="nullify",
                                                         LIST_VAR=data,
                                                         **self.attributes)
                                if new_value:
                                    new_list.appende(new_value)
                            new_value = new_list
                        else:
                            new_value  = render_jinja(action_param, mode="nullify",
                                                     LIST_VAR=data,
                                                     **self.attributes)

                        new_value = new_value.strip()
                        if new_value.startswith('[') and new_value.endswith(']'):
                            new_value = ast.literal_eval(new_value.replace('\n',''))
                            # Remove empty entries
                            new_value = [x for x in new_value if x]

                        new_value = self.handle_fields(action, new_value)

                        if new_value == 'SKIP_RULE':
                            defaults_by_id[idx] = False
                        elif new_value != 'SKIP_FIELD':
                            defaults_by_id[idx][action] = new_value
                        #else:
                        #    defaults_by_id[idx][action] = False
            else:
                new_value  = render_jinja(action_param, mode="nullify", **self.attributes)
                new_value = new_value.strip()
                new_value = self.handle_fields(action, new_value)
                if new_value != 'SKIP_FIELD':
                    defaults_for_list[action] = new_value
                #else:
                #    defaults_for_list[action] = False

            if action == ignore_field:
                ignore_list += [x.strip() for x in new_value.split(',')]
                continue


        if defaults_by_id:
            for collection_data in defaults_by_id.values():
                collection_data.update(defaults_for_list)
                outcome_selection.append(collection_data)
        else:
            outcome_selection.append(defaults_for_list)

        return outcome_selection, ignore_list


    def add_outcomes(self, rule, rule_outcomes, outcomes):
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
        cache = self.__class__.__qualname__.replace('.','')
        if self.cache_name:
            cache = self.cache_name
        if cache in db_host.cache:
            logger.debug(f"Using Rule Cache for {db_host.hostname}")
            return db_host.cache[cache]

        self.attributes = attributes
        self.hostname = db_host.hostname
        self.db_host = db_host
        rules = self.check_rule_match(db_host)
        db_host.cache[cache] = rules
        db_host.save()
        return rules
