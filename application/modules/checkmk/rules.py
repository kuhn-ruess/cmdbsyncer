#!/usr/bin/env python3
"""
Checkmk Rules
"""
from application.modules.rule.rule import Rule
from application.modules.debug import debug as print_debug
from application.modules.debug import ColorCodes
from application.modules.checkmk import poolfolder

class CheckmkRule(Rule): # pylint: disable=too-few-public-methods
    """
    Class to get actions for rule
    """
    found_poolfolder_rule = False # Spcific Helper for this kind of action
    db_host = False
    labels = {}

    @staticmethod
    def format_foldername(folder):
        """ Format Foldername """
        if not folder.startswith('/'):
            folder = "/" + folder
        if folder.endswith('/'):
            folder = folder[:-1]
        return folder.lower()


    def add_outcomes(self, rule_outcomes, outcomes):
        """ Handle the Outcomes """
        #pylint: disable=too-many-branches
        outcomes_to_return = [
            'ignore', 'ignore_host' # @TODO Remove ignore for ignore_host
        ]
        for outcome in rule_outcomes:
            # We add only the outcome of the
            # first matching rule action
            # exception are the folders

            # Prepare empty string to add later on subfolder if needed
            # We delete it anyway at the end, if it's stays empty

            outcomes.setdefault('move_folder',"")

            if outcome['action'] == 'move_folder':
                outcomes['move_folder'] += self.format_foldername(outcome['action_param'])

            if outcome['action'] == 'folder_pool':
                self.found_poolfolder_rule = True
                if self.db_host.get_folder():
                    outcomes['move_folder'] += self.db_host.get_folder()
                else:
                    # Find new Pool Folder
                    folder = poolfolder.get_folder()
                    if not folder:
                        raise Exception(f"No Pool Folder left for {self.db_host.hostname}")
                    folder = self.format_foldername(folder)
                    self.db_host.lock_to_folder(folder)
                    outcomes['move_folder'] += folder

            if outcome['action'] not in outcomes and \
                outcome['action'] in outcomes_to_return:
                print_debug(self.debug,
                            f"---- Added Outcome {outcome['action']} = {outcome['action_param']}")
                outcomes[outcome['action']] = outcome['action_param']

            print_debug(self.debug,
                        "- Handle Special options")

            if outcome['action'] == 'value_as_folder':
                search_tag = outcome['action_param']
                print_debug(self.debug,
                            f"---- value_as_folder matched, search tag '{search_tag}'")
                for tag, value in self.labels.items():
                    if search_tag == tag:
                        print_debug(self.debug, f"----- {ColorCodes.OKGREEN}Found tag"\
                                                f"{ColorCodes.ENDC}, add folder: '{value}'")
                        outcomes['move_folder'] += self.format_foldername(value)

            if outcome['action'] == 'tag_as_folder':
                search_value = outcome['action_param']
                print_debug(self.debug,
                            f"---- tag_as_folder matched, search value '{search_value}'")
                for tag, value in self.labels.items():
                    if search_value == value:
                        print_debug(self.debug, f"------ {ColorCodes.OKGREEN}Found value"\
                                                f"{ColorCodes.ENDC}, add folder: '{tag}'")
                        outcomes['move_folder'] += self.format_foldername(tag)

            # Cleanup in case not folder rule applies,
            # we have nothing to return to the plugins
            if not outcomes['move_folder']:
                del outcomes['move_folder']
        return outcomes



    def check_rule_match(self, db_host, labels):
        """
        Overwritten cause of folder_pool
        """

        hostname = db_host.hostname
        #pylint: disable=too-many-branches

        self.found_poolfolder_rule = False
        self.db_host = db_host
        self.labels = labels
        outcomes = self.check_rules(hostname, labels)
        # Cleanup Pool folder since no match
        # to a poolfolder rule anymore
        if not self.found_poolfolder_rule:
            if db_host.get_folder():
                old_folder = db_host.get_folder()
                db_host.lock_to_folder(False)
                poolfolder.remove_seat(old_folder)
        return outcomes
