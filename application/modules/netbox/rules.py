#!/usr/bin/env python3
"""
Netbox Rules
"""
#pylint: disable=too-few-public-methods
from application.modules.rule.rule import Rule
from application.helpers.syncer_jinja import render_jinja

#   . -- Devices
class NetboxVariableRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom Variables for Netbox Devices
    """

    name = "Netbox -> DCIM Device Attributes"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        sub_values = [
            'model'
        ]
        outcomes.setdefault('fields', {})
        outcomes.setdefault('do_not_update_keys', [])
        outcomes.setdefault('sub_fields', {})
        for outcome in rule_outcomes:
            action_param = outcome['param']
            field = outcome['action']
            if field == 'update_optout':
                fields = [str(x).strip() for x in action_param.split(',')]
                outcomes['do_not_update_keys'] += fields
            else:
                new_value  = render_jinja(action_param, mode="nullify",
                                         HOSTNAME=self.hostname, **self.attributes)

                if new_value in ['None', '']:
                    continue

                if field == 'serial':
                    new_value = new_value[:50]

                if field in sub_values:
                    outcomes['sub_fields'][field] = new_value.strip()
                else:
                    outcomes['fields'][field] = new_value.strip()

        return outcomes
#.
#   . -- IP Addresses
class NetboxIpamIPaddressRule(NetboxVariableRule):
    """
    Rules for IP Addresses 
    """
    name = "Netbox -> IPAM IP Attributes"

    def add_outcomes(self, rule, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        outcomes.setdefault('ips', [])
        sub_fields = [
        ]
        outcome_object = {}
        outcome_subfields_object = {}
        rule_name = rule['name']
        for outcome in rule_outcomes:
            action_param = outcome['param']
            action = outcome['action']
            new_value  = render_jinja(action_param, mode="nullify",
                                     HOSTNAME=self.hostname, **self.attributes)
            new_value = new_value.strip()
            if action == 'address' and not new_value:
                # early return
                return outcomes
            if action == "assigned":
                if action_param.lower() == 'false':
                    new_value = False
                else:
                    new_value = True

            if action in sub_fields:
                outcome_subfields_object[action] = new_value
            else:
                outcome_object[action] = new_value

        outcomes['ips'].append({'fields': outcome_object,
                                'sub_fields': outcome_subfields_object,
                                'by_rule': rule_name})

        return outcomes
#.
#   . -- Interfaces
class NetboxDevicesInterfaceRule(NetboxVariableRule):
    """
    Rules for Device Interfaces
    """
    name = "Netbox -> DCIM Interfaces"

    def add_outcomes(self, rule, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        # This function is called once per rule,
        # But can contain outcomes of more then one rule.
        # Here we match them together
        rule_name = rule['name']
        outcomes.setdefault('interfaces', [])
        outcome_object = {}
        outcome_subfields_object = {}
        sub_fields = [
            'ip_address',
            'netbox_device_id',
        ]
        for outcome in rule_outcomes:
            action_param = outcome['param']
            action = outcome['action']

            hostname = self.db_host.hostname

            new_value  = render_jinja(action_param, mode="nullify",
                                     HOSTNAME=hostname, **self.attributes)

            if action == 'name' and not new_value:
                # early return
                return outcomes

            new_value = new_value.strip()
            if new_value == "None":
                new_value = None
            if action == 'mac_address':
                if not new_value:
                    continue
                new_value = new_value.upper()
            if action == 'mtu':
                if not new_value:
                    continue
                new_value = int(new_value)
            if action in sub_fields:
                outcome_subfields_object[action] = new_value
            else:
                outcome_object[action] = new_value
        outcomes['interfaces'].append({'fields': outcome_object,
                                       'sub_fields': outcome_subfields_object,
                                       'by_rule': rule_name})
        return outcomes
#.
#   . -- Contacts
class NetboxContactRule(NetboxVariableRule):
    """
    Attribute Options for a Contact
    """
    name = "Netbox -> Tenancy Contacts"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        outcomes.setdefault('fields', {})
        for outcome in rule_outcomes:
            action_param = outcome['param']
            action = outcome['action']

            hostname = self.db_host.hostname

            new_value  = render_jinja(action_param, mode="nullify",
                                     HOSTNAME=hostname, **self.attributes).strip()

            if action == 'email':
                if not '@' in new_value:
                    continue
                if not new_value or new_value == '':
                    continue

            outcomes['fields'][action] = new_value
        return outcomes
#.
#   . -- Dataflow
class NetboxDataflowRule(NetboxVariableRule):
    """
    Attribute Options for a Dataflow
    """
    name = "Netbox -> Dataflow"

    def add_outcomes(self, rule, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        outcomes.setdefault('entries', [])
        outcome_object = {}
        rule_name = rule['name']
        for outcome in rule_outcomes:
            field_name = outcome['field_name']
            field_value = outcome['field_value']

            hostname = self.db_host.hostname

            new_value  = render_jinja(field_value, mode="nullify",
                                     HOSTNAME=hostname, **self.attributes).strip()

            if outcome['expand_value_as_list']:
                for list_value in new_value.split(','):
                    outcome_object = {}
                    outcome_object[field_name] = {
                            'value': list_value.strip(),
                            'use_to_identify': outcome['use_to_identify'],
                            'expand_value_as_list': outcome['expand_value_as_list'],
                            }
                    outcomes['entries'].append({'fields': outcome_object,
                                             'by_rule': rule_name})
            else:
                outcome_object[field_name] = {
                        'value': new_value,
                        'use_to_identify': outcome['use_to_identify'],
                        'expand_value_as_list': outcome['expand_value_as_list'],
                        }
                outcomes['entries'].append({'fields': outcome_object,
                                             'by_rule': rule_name})
        return outcomes
#.
