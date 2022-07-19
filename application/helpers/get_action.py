#!/usr/bin/env python3
"""
Get Action
"""

from application.models.rule import ActionRule
from application.helpers.match import match
from application.helpers.debug import debug as print_debug
from application.helpers.debug import ColorCodes
from application.helpers import poolfolder

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
    def format_foldername(folder):
        """ Format Foldername """
        if not folder.startswith('/'):
            folder = "/" + folder
        if folder.endswith('/'):
            folder = folder[:-1]
        return folder.lower()

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


    def _check_rule_match(self, db_host, labels):
        """
        Return True if rule matches
        """

        hostname = db_host.hostname
        #pylint: disable=too-many-branches
        outcomes = {}

        # List of outcomes to return without need of any handling here
        outcomes_to_return = [
            'ignore',
        ]
        # In this loop we collect all possible rule outcomes which lead to the
        # actions which happens to the host
        print_debug(self.debug, f"Debug Rules for {ColorCodes.UNDERLINE}{hostname}{ColorCodes.ENDC}")
        found_poolfolder_rule = False
        for rule in self.rules:
            rule_hit = False
            if rule['condition_typ'] == 'any':
                print_debug(self.debug,
                            f"--- Rule ANY can match (RuleID: {ColorCodes.OKBLUE}{rule['_id']}{ColorCodes.ENDC})")
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
                            f"--- Rule ALL must match (RuleID: {ColorCodes.OKBLUE}{rule['_id']}{ColorCodes.ENDC})")
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
                            f"--- Rule HIT cause 'Any condition can match' (RuleID: {ColorCodes.OKBLUE}{rule['_id']}{ColorCodes.ENDC})")
                rule_hit = True

            # Rule matches, get outcome
            if rule_hit:

                # Cleanup Poolfolder if needed
                for outcome in rule['outcome']:
                    # We add only the outcome of the
                    # first matching rule type
                    # exception are the folders

                    # Prepare empty string to add later on subfolder if needed
                    # We delete it anyway at the end, if it's stays empty

                    if outcome['type'] in ['source_folder', 'tag_as_source_folder']:
                        raise Exception(f"Please Migrate Rule {rule['_id']} in order to use normale Folder Outcomes")

                    outcomes.setdefault('move_folder',"")

                    if outcome['type'] == 'move_folder':
                        outcomes['move_folder'] += self.format_foldername(outcome['param'])

                    if outcome['type'] == 'folder_pool':
                        found_poolfolder_rule = True
                        if db_host.get_folder():
                            outcomes['move_folder'] += db_host.get_folder()
                        else:
                            # Find new Pool Folder
                            folder = poolfolder.get_folder()
                            if not folder:
                                raise Exception(f"No Pool Folder left for {hostname}")
                            folder = self.format_foldername(folder)
                            db_host.lock_to_folder(folder)
                            outcomes['move_folder'] += folder

                    if outcome['type'] not in outcomes and \
                        outcome['type'] in outcomes_to_return:
                        print_debug(self.debug,
                                    f"---- Added Outcome {outcome['type']} = {outcome['param']}")
                        outcomes[outcome['type']] = outcome['param']

                    print_debug(self.debug,
                                "- Handle Special options")

                    if outcome['type'] == 'value_as_folder':
                        search_tag = outcome['param']
                        print_debug(self.debug,
                                    f"---- value_as_folder matched, search tag '{search_tag}'")
                        for tag, value in labels.items():
                            if search_tag == tag:
                                print_debug(self.debug, f"----- {ColorCodes.OKGREEN}Found tag{ColorCodes.ENDC}, add folder: '{value}'")
                                outcomes['move_folder'] += self.format_foldername(value)

                    if outcome['type'] == 'tag_as_folder':
                        search_value = outcome['param']
                        print_debug(self.debug,
                                    f"---- tag_as_folder matched, search value '{search_value}'")
                        for tag, value in labels.items():
                            if search_value == value:
                                print_debug(self.debug, f"------ {ColorCodes.OKGREEN}Found value{ColorCodes.ENDC}, add folder: '{tag}'")
                                outcomes['move_folder'] += self.format_foldername(tag)

                    # Cleanup in case not folder rule applies,
                    # we have nothing to return to the plugins
                    if not outcomes['move_folder']:
                        del outcomes['move_folder']

                # If rule has matched, and option is set, we are done
                if rule['last_match']:
                    print_debug(self.debug, f"--- {ColorCodes.FAIL}Rule id {rule['_id']} was last_match{ColorCodes.ENDC}")
                    break
        # Cleanup Pool folder since no match
        # to a poolfolder rule anymore
        if not found_poolfolder_rule:
            if db_host.get_folder():
                old_folder = db_host.get_folder()
                db_host.lock_to_folder(False)
                poolfolder.remove_seat(old_folder)

        return outcomes


    def get_action(self, db_host, labels):
        """
        Return next Action for this Host
        """
        return self._check_rule_match(db_host, labels)
