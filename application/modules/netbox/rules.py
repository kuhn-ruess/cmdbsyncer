#!/usr/bin/env python3
"""
Netbox Rules
"""
from application import logger
from application.modules.rule.rule import Rule
from application.helpers.syncer_jinja import render_jinja

class NetboxVariableRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom Variables for Netbox Devices
    """

    name = "Netbox -> DCIM Device Attributes"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        outcomes.setdefault('custom_attributes', [])
        outcomes.setdefault('do_not_update_keys', [])
        for outcome in rule_outcomes:
            action_param = outcome['param']
            action = outcome['action']
            if action == 'custom_field':
                new_value  = render_jinja(action_param, mode="nullify",
                                         HOSTNAME=self.hostname, **self.attributes)
                try:
                    key, value = new_value.split(':')
                    outcomes['custom_attributes'].append((key, value.strip()))
                except ValueError:
                    logger.debug(f"Cant split '{new_value}' into Key Value Pair")
            elif action == 'update_optout':
                fields = [str(x).strip() for x in action_param.split(',')]
                outcomes['do_not_update_keys'] += fields
            else:
                outcomes[outcome['action']] = outcome['param'].strip()

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

            new_value  = render_jinja(action_param, mode="nullify",
                                     HOSTNAME=self.hostname, **self.attributes)
            new_value = new_value.strip()
            if action == "assigned":
                if action_param.lower() == 'false':
                    new_value = False
                else:
                    new_value = True


            outcomes[action] = new_value
        return outcomes

class NetboxDevicesInterfaceRule(NetboxVariableRule):
    name = "Netbox -> DCIM Interfaces"

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

            outcome_object[action] = new_value.strip()
        outcomes['interfaces'].append(outcome_object)
        return outcomes

class NetboxContactRule(NetboxVariableRule):
    name = "Netbox -> Tenancy Contacts"

    def add_outcomes(self, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        outcome_object = {}
        for outcome in rule_outcomes:
            action_param = outcome['param']
            action = outcome['action']

            hostname = self.db_host.hostname

            new_value  = render_jinja(action_param, mode="nullify",
                                     HOSTNAME=hostname, **self.attributes)

            outcomes[action] = new_value.strip()
        return outcomes
