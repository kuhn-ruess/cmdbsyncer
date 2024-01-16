#!/usr/bin/env python3
"""
i-doit Rules
"""
import jinja2
from application.modules.rule.rule import Rule
from ast import literal_eval

class IdoitVariableRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom variables for i-doit
    """

    name = "i-doit -> Custom attributes"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """

        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            action = outcome['action']

            if action == 'id_category':
                tpl = jinja2.Template(outcome['param'])
                hostname = self.db_host.hostname
                new_value = tpl.render(HOSTNAME=hostname, **self.attributes)
                as_dict = literal_eval(new_value)
                outcomes.setdefault('id_category', {})
                outcomes['id_category'].update(as_dict)
            else:
                outcomes[outcome['action']] = outcome['param']
        return outcomes
