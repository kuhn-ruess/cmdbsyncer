#!/usr/bin/env python3
"""
Checkmk Rules
"""
#pylint: disable=import-error
#pylint: disable=logging-fstring-interpolation
import ast
from application import app
from application.helpers.syncer_jinja import render_jinja
from application import logger
from application.modules.rule.rule import Rule
from application.modules.debug import debug as print_debug
from application.modules.debug import ColorCodes
from application.modules.checkmk import poolfolder

class CheckmkRulesetRule(Rule): # pylint: disable=too-few-public-methods, too-many-locals, too-many-nested-blocks
    """
    Rule to create Rulesets in Checkmk
    """

    name = "Checkmk -> CMK Rules Managment"


    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Add matching Rules to the set
        """
        for outcome in rule_outcomes:
            ruleset_type = outcome['ruleset']
            outcomes.setdefault(ruleset_type, [])
            outcomes[ruleset_type].append(outcome)
        return outcomes


class DefaultRule(Rule):
    """
    Just adds all to the set
    """

    def __init__(self, name="default"):
        """
        Init
        """
        super().__init__()

        if not self.name:
            self.name = name

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Add matching Rules to the set
        """
        outcomes.setdefault('default', [])
        for outcome in rule_outcomes:
            outcomes['default'].append(outcome)
        return outcomes

class CheckmkRule(Rule): # pylint: disable=too-few-public-methods
    """
    Class to get actions for rule
    """

    name = "Checkmk -> Export Rules"

    found_poolfolder_rule = False # Spcific Helper for this kind of action
    db_host = False

    def fix_and_format_foldername(self, folder):
        """ Format Foldername
        Remove Extra Folder Attributes
        """
        parts = []
        for folder_part in folder.split('/'):
            splitted = folder_part.split('|')
            if splitted[0]:
                parts.append(splitted[0])
        new_folder = "/" + "/".join(parts)

        new_folder = self.replace(new_folder, exceptions=['/'])
        if app.config['CMK_LOWERCASE_FOLDERNAMES']:
            new_folder = new_folder.lower()
        new_path = self.replace(new_folder, regex='[^a-z A-Z 0-9/_-]')
        if new_path[-1] == '/':
            return new_path[:-1]
        return new_path

    def format_foldername(self, folder):
        """
        Fix invalid chars in Folder Path
        """
        parts = []
        for folder_part in folder.split('/'):
            splitted = folder_part.split('|')
            path = splitted[0]
            if app.config['CMK_LOWERCASE_FOLDERNAMES']:
                path = path.lower()
            folder_name = self.replace(self.replace(path, exceptions=['/']),
                                       regex='[^a-z A-Z 0-9/_-]')
            if len(splitted) == 2:
                folder_name += "|" + splitted[1]
            if folder_name:
                parts.append(folder_name)
        new_path = "/" + "/".join(parts)
        if new_path[-1] == '/':
            return new_path[:-1]
        return new_path

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """ Handle the Outcomes """
        #pylint: disable=too-many-branches, too-many-statements
        #pylint: disable=too-many-locals, too-many-nested-blocks

        possible_outcomes = [
            ('move_folder',""),
            ('extra_folder_options',""),
            ('attributes', []),
            ('custom_attributes', {}),
            ('remove_attributes', []),
            ('remove_if_attributes', []),
            ('create_cluster', []),
            ('create_folder', ""),
            ('create_folder_extra_folder_options', ""),
            ('prefix_labels', False),
            ('only_update_prefixed_labels', False),
            ('dont_update_prefixed_labels', []),
            ('parents', []),
            ('dont_move', False),
            ('dont_update', False),
        ]
        for choice, default in possible_outcomes:
            outcomes.setdefault(choice, default)

        print_debug(self.debug,
                    "- Handle Special options")

        hostname = self.db_host.hostname

        for outcome in rule_outcomes:
            # We add only the outcome of the
            # first matching rule action
            # exception are the folders



            action_param = outcome['action_param']
            if outcome['action'] == 'move_folder':
                new_value = action_param
                new_value = render_jinja(new_value, mode="nullify", **self.attributes)

                outcomes['extra_folder_options'] += self.format_foldername(new_value)
                outcomes['move_folder'] += self.fix_and_format_foldername(new_value)


            if outcome['action'] == 'dont_move':
                outcomes['dont_move'] = True

            if outcome['action'] == 'dont_update':
                outcomes['dont_update'] = True

            if outcome['action'] == 'prefix_labels':
                outcomes['label_prefix'] = action_param

            if outcome['action'] == 'only_update_prefixed_labels':
                outcomes['only_update_prefixed_labels'] = action_param

            if outcome['action'] == 'dont_update_prefixed_labels':
                if action_param not in outcomes['dont_update_prefixed_labels']:
                    outcomes['dont_update_prefixed_labels'].append(action_param)

            if outcome['action'] == 'create_folder':
                new_value = action_param
                new_value = render_jinja(new_value, mode="nullify", **self.attributes)

                outcomes['create_folder_extra_folder_options'] += self.format_foldername(new_value)
                outcomes['create_folder'] += self.fix_and_format_foldername(new_value)

            if outcome['action'] == 'folder_pool':
                self.found_poolfolder_rule = True
                if self.db_host.get_folder():
                    pool_folder = self.db_host.get_folder()
                    outcomes['extra_folder_options'] += pool_folder
                    outcomes['move_folder'] += pool_folder
                else:
                    # Find new Pool Folder
                    only_pools = None
                    if action_param:
                        only_pools = [x.strip() for x in action_param.split(',')]
                    folder = poolfolder.get_folder(only_pools)
                    if not folder:
                        raise ValueError(f"No Pool Folder left for {self.db_host.hostname}")
                    folder = self.format_foldername(folder)
                    self.db_host.lock_to_folder(folder)
                    outcomes['extra_folder_options'] += folder
                    outcomes['move_folder'] += folder

            if outcome['action'] == 'attribute':
                outcomes['attributes'].append(action_param)

            if outcome['action'] == "remove_attr_if_not_set":
                action_render = render_jinja(action_param, mode="nullify", **self.attributes)

                for attribute in action_render.split(','):
                    attribute = attribute.strip()
                    outcomes['remove_if_attributes'].append(attribute)

            if outcome['action'] == 'custom_attribute':
                action_render = render_jinja(action_param, mode="nullify", **self.attributes)

                action_render = self.replace(action_render, exceptions=[
                                                        " ", '/', ',','|'
                                                    ]) # Replace Chars not working in Checkmk


                python_detectors = ['[', '{']
                if action_render:
                    attrs = action_render.split('||')
                    for attr_pair in attrs:
                        if not attr_pair:
                            continue
                        try:
                            new_key, new_value = attr_pair.split(':', 1)
                            new_key = new_key.strip()
                            new_value = new_value.strip()
                            if any(x in new_value for x in python_detectors):
                                try:
                                    new_value = ast.literal_eval(new_value)
                                except SyntaxError:
                                    pass

                            if str(new_value).lower() in ['none', 'false']:
                                outcomes['remove_attributes'].append(new_key)
                            elif new_key and new_value:
                                outcomes['custom_attributes'][new_key] = new_value
                        except ValueError:
                            logger.debug(f"Cant split '{attr_pair}'")

            if outcome['action'] == "set_parent":
                value = action_param
                new_value = render_jinja(value, **self.attributes)
                for parent in new_value.split(','):
                    parent = parent.strip()
                    if parent and parent not in outcomes['parents']:
                        outcomes['parents'].append(parent)


            if outcome['action'] == 'value_as_folder':
                search_tag = action_param
                print_debug(self.debug,
                            f"---- value_as_folder matched, search tag '{search_tag}'")
                for tag, value in self.attributes.items():
                    if search_tag == tag:
                        if value and value != 'null':
                            print_debug(self.debug, f"----- {ColorCodes.OKGREEN}Found tag"\
                                                    f"{ColorCodes.ENDC}, add folder: '{value}'")
                            outcomes['extra_folder_options'] += self.format_foldername(value)
                            outcomes['move_folder'] += self.fix_and_format_foldername(value)
                        else:
                            print_debug(self.debug, \
                                f"----- {ColorCodes.OKGREEN}Found tag but content null")

            if outcome['action'] == 'tag_as_folder':
                search_value = action_param
                print_debug(self.debug,
                            f"---- tag_as_folder matched, search value '{search_value}'")
                for tag, value in self.attributes.items():
                    if search_value == value:
                        if value and value != 'null':
                            print_debug(self.debug, f"------ {ColorCodes.OKGREEN}Found value"\
                                                    f"{ColorCodes.ENDC}, add folder: '{tag}'")
                            outcomes['extra_folder_options'] += self.format_foldername(tag)
                            outcomes['move_folder'] += self.fix_and_format_foldername(tag)
                        else:
                            print_debug(self.debug, \
                                f"----- {ColorCodes.OKGREEN}Found value but content null")

            if outcome['action'] == 'create_cluster':
                params = [x.strip() for x in action_param.split(',')]
                for node_tag in params:
                    if node_tag.endswith('*'):
                        for tag, value in self.attributes.items():
                            if tag.startswith(node_tag[:-1]):
                                outcomes['create_cluster'].append(value)
                    else:
                        if node := self.attributes.get(node_tag):
                            outcomes['create_cluster'].append(node)

        # Cleanup in case not folder rule applies,
        # we have nothing to return to the plugins
        for choice, _ in possible_outcomes:
            if not outcomes[choice]:
                del outcomes[choice]

        print_debug(self.debug, "")
        return outcomes

    def check_rule_match(self, db_host):
        """
        Overwritten cause of folder_pool
        """

        hostname = db_host.hostname
        #pylint: disable=too-many-branches

        self.found_poolfolder_rule = False
        self.db_host = db_host
        outcomes = self.check_rules(hostname)
        # Cleanup Pool folder since no match
        # to a poolfolder rule anymore
        if not self.found_poolfolder_rule:
            if db_host.get_folder():
                old_folder = db_host.get_folder()
                db_host.lock_to_folder(False)
                poolfolder.remove_seat(old_folder)
        return outcomes
