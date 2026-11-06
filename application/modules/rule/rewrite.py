#!/usr/bin/env python3
"""
Rewrite
"""
import ast
from application.modules.rule.rule import Rule
from application import logger
from application.helpers.syncer_jinja import render_jinja

class Rewrite(Rule):
    """
    Rewrite Attributes
    """

    name = "Rewrite"

    def get_attribute_name(self, outcome):
        """
        Get Old and New Attribute Name
        """
        old_name = outcome['old_attribute_name']
        new_name = False
        if mode := outcome['overwrite_name']:
            # Default in case of String:
            new_name = outcome['new_attribute_name']
            if mode == 'jinja':
                new_name = render_jinja(new_name, mode="nullify",
                                        HOSTNAME=self.hostname,
                                        **self.first_match_variables(),
                                        **self.attributes)
        return old_name, new_name

    def get_new_attribute_value(self, outcome, attribute_name):
        """
        Rewrite the Value
        """
        old_value = self.attributes.get(attribute_name, "")
        # The old Value stays the new Value, if not overwritten
        new_value = old_value
        value_mode = outcome['overwrite_value']
        # 'None' is the model default of a rule that chose no operation. Only
        # a value given with it replaces the old one.
        if value_mode and (value_mode != 'None' or outcome.get('new_value')):
            # Default in case of String
            if  new_value := outcome.get('new_value'):
                if value_mode == 'split':
                    # The index follows the last colon, the separator may be one
                    what, _, index = new_value.rpartition(':')
                    try:
                        splited = old_value.split(what)
                        new_value = splited[int(index)]
                    except (IndexError, TypeError, ValueError, AttributeError):
                        logger.debug("Cant Split Value, old one returned")
                        return old_value
                elif value_mode == 'jinja':
                    new_value = render_jinja(new_value, mode="nullify",
                                             **self.first_match_variables(),
                                             HOSTNAME=self.hostname, **self.attributes)
        return new_value

    def get_list_for_attribute(self, attribute_name, template):
        """
        Fetch Attributes Value and convert outcome to list
        """
        value = self.attributes.get(attribute_name, "[]")
        value = render_jinja(template, mode="nullify", result=value, **self.attributes)
        try:
            attribute_list = ast.literal_eval(value.replace('\n',''))
        except (ValueError, SyntaxError):
            attribute_list = []
        return attribute_list


    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Rewrite matching Attribute
        """
        for outcome in rule_outcomes:

            # A Attribute names list is used,
            # for the case where the mode returns muliple new attributes.
            # But they will always have the same value
            attributes = []
            old_name, current_name = self.get_attribute_name(outcome)
            if outcome['overwrite_name'] == 'convert_list':
                attributes += self.get_list_for_attribute(old_name, current_name)
            elif current_name:
                outcomes[f'del_{old_name}'] = True
                attributes.append(current_name)
            else:
                # If we have no new name, the old stays as current one
                current_name = old_name
                attributes.append(current_name)

            # We pass the old name, since the attributes store of the host hast the value
            # stilles stored under this old name
            new_value = self.get_new_attribute_value(outcome, old_name)
            # An empty result only counts when it is the attribute's own value:
            # a rename must keep 0, False or '', a missing attribute stays missing.
            if new_value or (old_name in self.attributes
                             and new_value == self.attributes[old_name]):
                for name in attributes:
                    outcomes[f'add_{name}'] = new_value
                    # Make new Attribute also available to be used in
                    # in all of the following outcomes
                    self.attributes[name] = new_value

        return outcomes
