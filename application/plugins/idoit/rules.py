#!/usr/bin/env python3
"""
i-doit Rules
"""
from ast import literal_eval
import jinja2
from application.helpers.syncer_jinja import render_jinja
from application.modules.rule.rule import Rule

class IdoitVariableRule(Rule):
    """
    Add custom variables for i-doit
    """

    name = "i-doit -> Custom attributes"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """

        for outcome in rule_outcomes:
            action = outcome['action']

            if action == 'id_category':
                try:
                    hostname = self.db_host.hostname
                    new_value = render_jinja(
                        outcome['param'],
                        mode='raise',
                        replace_newlines=False,
                        HOSTNAME=hostname,
                        **self.attributes,
                    )
                    as_dict = literal_eval(new_value)
                    outcomes.setdefault('id_category', {})
                    outcomes['id_category'].update(as_dict)
                except jinja2.exceptions.UndefinedError:
                    pass
            elif action == 'id_object_description':
                hostname = self.db_host.hostname
                new_value = render_jinja(
                    outcome['param'],
                    replace_newlines=False,
                    HOSTNAME=hostname,
                    **self.attributes,
                )
                outcomes['description'] = new_value
            elif action == "ignore_host":
                outcomes['ignore_host'] = True
            else:
                outcomes[outcome['action']] = outcome['param']
        return outcomes
