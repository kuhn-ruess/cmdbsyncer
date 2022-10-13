#!/usr/bin/env python3
"""
Get CheckmkAction
"""

from application.models.rule import ActionRule
from application.helpers.action import Action
from application.helpers.debug import debug as print_debug
from application.helpers.debug import ColorCodes
from application.helpers import poolfolder

class GetCmkAction(Action): # pylint: disable=too-few-public-methods
    """
    Class to get actions for rule
    """
    found_poolfolder_rule = False # Spcific Helper for this kind of action
    db_host = False
    labels = {}


    def __init__(self, debug=False):
        """
        Prepare Rules
        """
        self.rules = [x.to_mongo() for x in ActionRule.objects(enabled=True).order_by('sort_field')]
        self.debug = debug

    @staticmethod
    def format_foldername(folder):
        """ Format Foldername """
        if not folder.startswith('/'):
            folder = "/" + folder
        if folder.endswith('/'):
            folder = folder[:-1]
        return folder.lower()


    def add_outcomes(self, rule, outcomes):
        """ Handle the Outcomes """
        #pylint: disable=too-many-branches
        outcomes_to_return = [
            'ignore', 'ignore_host' # @TODO Remove ignore for ignore_host
        ]
        for outcome in rule['outcome']:
            # We add only the outcome of the
            # first matching rule type
            # exception are the folders

            # Prepare empty string to add later on subfolder if needed
            # We delete it anyway at the end, if it's stays empty

            outcomes.setdefault('move_folder',"")

            if outcome['type'] == 'move_folder':
                outcomes['move_folder'] += self.format_foldername(outcome['param'])

            if outcome['type'] == 'folder_pool':
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
                for tag, value in self.labels.items():
                    if search_tag == tag:
                        print_debug(self.debug, f"----- {ColorCodes.OKGREEN}Found tag"\
                                                f"{ColorCodes.ENDC}, add folder: '{value}'")
                        outcomes['move_folder'] += self.format_foldername(value)

            if outcome['type'] == 'tag_as_folder':
                search_value = outcome['param']
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
        Overwritten cause of foulder_pool
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
