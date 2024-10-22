#!/usr/bin/env python3
"""
Netbox Rules
"""
from application.modules.rule.rule import Rule
from application.helpers.syncer_jinja import render_jinja

class NetboxVariableRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom Variables for Ansible
    """

    name = "Netbox -> Custom Attributes"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            outcomes[outcome['action']] = outcome['param']
        return outcomes

class NetboxIpamIPaddressRule(NetboxVariableRule):
    name = "Netbox -> IPAM IP Attributes"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        for outcome in rule_outcomes:
            action_param = outcome['param']
            action = outcome['action']

            hostname = self.db_host.hostname

            new_value  = render_jinja(action_param, mode="nullify",
                                     HOSTNAME=hostname, **self.attributes)

            if action == "assigned":
                if action_param.lower() == 'false':
                    new_value = False
                else:
                    new_value = True
            outcomes[action] = new_value
        return outcomes

class NetboxDevicesInterfaceRule(NetboxVariableRule):
    name = "Netbox -> Device Interfaces"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        outcomes.setdefault('interfaces', [])
        outcome_object = {}
        for outcome in rule_outcomes:
            action_param = outcome['param']
            action = outcome['action']

            hostname = self.db_host.hostname

            new_value  = render_jinja(action_param, mode="nullify",
                                     HOSTNAME=hostname, **self.attributes)

            outcome_object[action] = new_value
        outcomes['interfaces'].append(outcome_object)
        return outcomes
