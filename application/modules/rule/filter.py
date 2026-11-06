#!/usr/bin/env python3
"""
Filter
"""
from application.modules.rule.rule import Rule

class Filter(Rule):
    """
    Filter Attributes
    """

    name = "Filter"

    def _whitelist_attribute(self, attribute_name, outcomes):
        """
        Keep one attribute by its name, or all starting with it for name*
        """
        if not attribute_name.endswith('*'):
            # 0 and False are values, only "no value" stays out
            if self.attributes.get(attribute_name) not in (None, ''):
                outcomes[attribute_name] = self.attributes[attribute_name]
            return
        real_name = attribute_name[:-1]
        for attribute in self.attributes:
            if attribute.startswith(real_name):
                outcomes[attribute] = self.attributes[attribute]

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Filter if attributes match to a rule
        """
        for outcome in rule_outcomes:
            if outcome['action'] == 'whitelist_attribute':
                self._whitelist_attribute(outcome['attribute_name'], outcomes)

            if outcome['action'] == 'whitelist_attribute_value':
                search_value = outcome['attribute_name']
                exact_search = True
                if search_value.endswith('*'):
                    exact_search = False
                    search_value = search_value[:-1]
                for attr, attr_value in self.attributes.items():
                    if exact_search:
                        if str(attr_value) == search_value:
                            outcomes[attr] = attr_value
                    elif str(attr_value).startswith(search_value):
                        outcomes[attr] = attr_value

            if outcome['action'] == 'ignore_hosts':
                outcomes['ignore_host'] = True
        return outcomes
