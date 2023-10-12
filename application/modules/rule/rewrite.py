#!/usr/bin/env python3
"""
Rewrite
"""
#pylint: disable=logging-fstring-interpolation, bare-except, too-many-branches, too-many-locals
import re
import jinja2
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
            # Save inital Attribute value too have it even the attribute name changes
            old_value = self.attributes.get(attribute_name, "")
            new_attribute_name = False
            if mode := outcome['overwrite_name']:
                print(1)
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
                            logger.debug("Cant Split Rewrite Attribute")
                elif mode == 'jinja':
                    tpl = jinja2.Template(new_attribute_name)
                    new_attribute_name = tpl.render(HOSTNAME=self.hostname, **self.attributes)
                    if self.attributes.get(attribute_name):
                        outcomes[f'add_{new_attribute_name}'] = self.attributes[attribute_name]
                        outcomes[f'del_{attribute_name}'] = True
                    else:
                        # This can happen when we create a complete new one, 
                        # there is now old value, and tis is correctly set in the   
                        # Overwrite Value part
                        outcomes[f'add_{new_attribute_name}'] = None


            if value_mode := outcome['overwrite_value']:
                print(2)
                if new_attribute_name:
                    # if overwriten before, write overwrite
                    attribute_name = new_attribute_name
                if 'new_value' not in outcome:
                    continue
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
                        logger.debug("Cant Split Value")
                elif value_mode == '':
                    tpl = jinja2.Template(new_value)
                    new_value = tpl.render(HOSTNAME=self.hostname, **self.attributes)
                    outcomes[f'add_{attribute_name}'] = new_value
                    print(f"Created {new_value}")
        return outcomes
