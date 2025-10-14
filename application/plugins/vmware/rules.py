#!/usr/bin/env python3
"""
Vmware Rules
"""
#pylint: disable=too-few-public-methods
from application.modules.rule.rule import Rule
from application.helpers.syncer_jinja import render_jinja


#   . -- Custom Attributes
class VmwareCustomAttributesRule(Rule):# pylint: disable=too-few-public-methods
    """
    Define Custom Attributes in Vmware
    """

    name = "VMware -> Custom Attributes"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Add Attributes to VMware
        """
        # pylint: disable=too-many-nested-blocks
        outcomes.setdefault('attributes', {})
        for outcome in rule_outcomes:
            attr_name = outcome['attribute_name']
            attr_value = outcome['attribute_value']

            attr_value  = render_jinja(attr_value, mode="nullify", **self.attributes)
            outcomes['attributes'][attr_name] = attr_value
        return outcomes
#.
