#!/usr/bin/env python3
"""
i-doit Rules
"""
from ast import literal_eval
import jinja2
from application.modules.rule.rule import Rule

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
                try:
                    tpl = jinja2.Template(outcome['param'], undefined=jinja2.StrictUndefined)
                    hostname = self.db_host.hostname
                    new_value = tpl.render(HOSTNAME=hostname, **self.attributes)
                    as_dict = literal_eval(new_value)
                    outcomes.setdefault('id_category', {})
                    outcomes['id_category'].update(as_dict)
                except jinja2.exceptions.UndefinedError:
                    pass
            elif action == 'id_object_description':
                tpl = jinja2.Template(outcome['param'])
                hostname = self.db_host.hostname
                new_value = tpl.render(HOSTNAME=hostname, **self.attributes)
                outcomes['description'] = new_value
            else:
                outcomes[outcome['action']] = outcome['param']
        return outcomes
