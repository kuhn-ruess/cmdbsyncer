#!/usr/bin/env python3
"""
Custom Attributes for Host
"""
from application.modules.rule.rule import Rule
from application.helpers.syncer_jinja import render_jinja



class CustomAttributeRule(Rule):
    """
    Return Custom Attributes for given Host
    """

    name = "Custom Attributes"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Add the new Attributes
        """
        for outcome in rule_outcomes:
            if not outcome:
                continue
            attribute_value = outcome['attribute_value']
            if attribute_value == 'True':
                attribute_value = True
            elif attribute_value == 'False':
                attribute_value = False
            elif (isinstance(attribute_value, str)
                    and '{{' not in attribute_value
                    and '{%' not in attribute_value):
                # Literal string — no Jinja syntax, skip the render
                # pipeline. At sync scale (N hosts × M matched rules)
                # this avoids one Jinja parse/render per outcome.
                attribute_value = attribute_value.strip()
            else:
                attribute_value = render_jinja(attribute_value, mode="nullify",
                                             FIRST_MATCHING_TAG=self.first_matching_tag,
                                             FIST_MATCHING_VALUE=self.first_matching_value,
                                             HOSTNAME=self.hostname, **self.attributes)
            outcomes[outcome['attribute_name']] = attribute_value
        return outcomes
