#!/usr/bin/env python3
"""
Rewrite
"""
import re
from application.modules.rule.rule import Rule
from application import logger

class Rewrite(Rule):# pylint: disable=too-few-public-methods
    """
    Rewrite Attributes
    """

    name = "Rewrite"
    rewrite_cache = {}

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Rewrite matching Attribute
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            attribute_name = outcome['old_attribute_name']
            new_attribute_name = False
            if mode := outcome['overwrite_name']:
                new_attribute_name = outcome['new_attribute_name']
                if mode == 'regex':
                    pattern = attribute_name
                    # Can may be simplified since i heared Python
                    # Handles the cache anyway
                    if not self.rewrite_cache.get(pattern):
                        self.rewrite_cache[pattern] = re.compile(pattern)
                    for key, value in self.attributes.items():
                        if self.rewrite_cache[pattern].match(key):
                            outcomes[f'add_{new_attribute_name}'] = value
                            outcomes[f'del_{key}'] = True
                elif mode == 'string':
                    if self.attributes.get(attribute_name):
                        outcomes[f'add_{new_attribute_name}'] = self.attributes[attribute_name]
                        outcomes[f'del_{attribute_name}'] = True
                elif mode == 'split':
                    if self.attributes.get(attribute_name):
                        what, index = new_attribute_name.split(':')
                        try:
                            new_attribute_name = new_attribute_name.split(what)[int(index)]
                            outcomes[f'add_{new_attribute_name}'] = self.attributes[attribute_name]
                            outcomes[f'del_{attribute_name}'] = True
                        except:
                            logger.debug(f"Cant Split Rewrite Attribute")


            if value_mode := outcome['overwrite_value']:
                if new_attribute_name:
                    # if overwriten before, write overwrite
                    attribute_name = new_attribute_name
                old_value = self.attributes[attribute_name]
                new_value = outcome['new_value']

                if value_mode == 'regex':
                    pattern = new_value
                    # Can may be simplified since i heared Python
                    # Handles the cache anyway
                    if not self.rewrite_cache.get(pattern):
                       self.rewrite_cache[pattern] = re.compile(pattern)
                    for key, value in self.attributes.items():
                       if self.rewrite_cache[pattern].match(key):
                           outcomes[f'add_{attribute_name}'] = value
                elif value_mode == 'string':
                    outcomes[f'add_{attribute_name}'] = new_value
                elif value_mode == 'split':
                    what, index = new_value.split(':')
                    try:
                        splited = old_value.split(what)
                        outcomes[f'add_{attribute_name}'] = splited[int(index)]
                    except:
                        logger.debug(f"Cant Split Value")
        print(outcomes)
        return outcomes
