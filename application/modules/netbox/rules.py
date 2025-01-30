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
            'model',
        ]
        outcomes.setdefault('fields', {})
        outcomes.setdefault('custom_fields', {})
        outcomes.setdefault('do_not_update_keys', [])
        outcomes.setdefault('sub_fields', {})
        for outcome in rule_outcomes:
            action_param = outcome['param']
            field = outcome['action']
            if field == 'update_optout':
                fields = [str(x).strip() for x in action_param.split(',')]
                outcomes['do_not_update_keys'] += fields
            elif field == 'custom_field':
                try:
                    new_value  = render_jinja(action_param, mode="nullify",
                                             HOSTNAME=self.hostname, **self.attributes)
                    custom_key, custom_value = new_value.split(':')
                    outcomes['custom_fields'][custom_key] = {'value': custom_value}
                except ValueError:
                    continue
            else:
                new_value  = render_jinja(action_param, mode="nullify",
                                         HOSTNAME=self.hostname, **self.attributes)

                #if new_value in ['None', '']:
                #    continue

                if field == 'serial':
                    new_value = new_value[:50]

                if field in sub_values:
                    outcomes['sub_fields'][field] = {'value': new_value.strip()}
                else:
                    outcomes['fields'][field] = {'value': new_value.strip()}
        return outcomes
#.
#   . -- Cluster Rule
class NetboxCluserRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom Variables for Cluster
    """

    name = "Netbox -> Virtualization Cluster"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        sub_values = [
        ]
        outcomes.setdefault('fields', {})
        outcomes.setdefault('custom_fields', {})
        outcomes.setdefault('sub_fields', {})
        for outcome in rule_outcomes:
            action_param = outcome['param']
            field = outcome['action']
            if field == 'custom_field':
                try:
                    new_value  = render_jinja(action_param, mode="nullify",
                                             HOSTNAME=self.hostname, **self.attributes)
                    custom_key, custom_value = new_value.split(':')
                    outcomes['custom_fields'][custom_key] = {'value': custom_value}
                except ValueError:
                    continue
            else:
                new_value  = render_jinja(action_param, mode="nullify",
                                         HOSTNAME=self.hostname, **self.attributes)

                if new_value in ['None', '']:
                    continue

                if field in sub_values:
                    outcomes['sub_fields'][field] = {'value': new_value.strip()}
                else:
                    outcomes['fields'][field] = {'value': new_value.strip()}

        return outcomes
#.
#   .-- Virutal Machines
class NetboxVirutalMachineRule(Rule):# pylint: disable=too-few-public-methods
    """
    Add custom Variables for Virutal Machines
    """

    name = "Netbox -> Virtualization Machines"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        sub_values = [
        ]
        outcomes.setdefault('fields', {})
        outcomes.setdefault('custom_fields', {})
        outcomes.setdefault('sub_fields', {})
        for outcome in rule_outcomes:
            action_param = outcome['param']
            field = outcome['action']
            if field == 'custom_field':
                try:
                    new_value  = render_jinja(action_param, mode="nullify",
                                             HOSTNAME=self.hostname, **self.attributes)
                    custom_key, custom_value = new_value.split(':')
                    outcomes['custom_fields'][custom_key] = {'value': custom_value.strip()}
                except ValueError:
                    continue
            else:
                new_value  = render_jinja(action_param, mode="nullify",
                                         HOSTNAME=self.hostname, **self.attributes)

                if new_value in ['None', '']:
                    continue

                if field in sub_values:
                    outcomes['sub_fields'][field] = {'value': new_value.strip()}
                else:
                    outcomes['fields'][field] = {'value': new_value.strip()}

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
        ignored_ips = []

        outcome_selection, ignored_ips =\
                self.get_multilist_outcomes(rule_outcomes, 'ignore_ip')

        for entry in outcome_selection:
            outcome_object = {}
            outcome_subfields_object = {}
            for key, value in entry.items():
                if key == 'ignore_ip':
                    continue
                if isinstance(value, str):
                    value = value.strip()
                if key in sub_fields:
                    outcome_subfields_object[key] = {'value': value}
                else:
                    outcome_object[key] = {'value': value}


            # The Outcome can contain a list of IPs,
            # and in the current state it's just a list.
            # Ignore objects therfore will be handled in plugin
            if outcome_object:
                outcomes['ips'].append({'fields': outcome_object,
                                               'sub_fields': outcome_subfields_object,
                                               'ignore_list': ignored_ips,
                                               'by_rule': rule_name})
        return outcomes
#.
#   . -- IPAM Prefixes
class NetboxIpamPrefixRule(NetboxVariableRule):
    """
    Rules for IPAM Prefixes
    """
    name = "Netbox -> IPAM Prefixes"


    def add_outcomes(self, rule, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        outcomes.setdefault('prefixes', [])
        sub_fields = [
        ]
        outcome_object = {}
        outcome_subfields_object = {}
        rule_name = rule['name']

        outcome_selection, _ignorelist =\
                self.get_multilist_outcomes(rule_outcomes, False)


        for entry in outcome_selection:
            outcome_object = {}
            outcome_subfields_object = {}
            prefixes = []
            for key, value in entry.items():
                if key == 'prefix':
                    prefixes = value
                elif key in sub_fields:
                    outcome_subfields_object[key] = {'value': value}
                else:
                    outcome_object[key] = {'value': value}

            for prefix in prefixes:
                if prefix in ['127.0.0.0/8']:
                    continue
                if outcome_object:
                    new_object  = outcome_object.copy()
                    new_object['prefix'] = {'value': prefix}
                    outcomes['prefixes'].append({'fields': new_object,
                                                   'sub_fields': outcome_subfields_object,
                                                   'by_rule': rule_name})
        return outcomes
#.
#   . -- Interfaces
class NetboxInterfaceRule(NetboxVariableRule):
    """
    Rules for Device Interfaces
    """
    name = "Netbox -> DCIM/ Virtualization Interfaces"


    def handle_fields(self, field_name, field_value):
        """
        Special Ops for Interfaces
        """
        if field_name == 'name' and not field_value:
            return "SKIP_RULE"

        if field_name == 'name':
            field_value = field_value[:64]

        field_value = field_value.strip()
        if field_value == "None":
            field_value = None
        if field_name == 'mac_address':

            if not field_value:
                return "SKIP_FIELD"
            field_value = field_value.upper()[:17]
        if field_name == 'mtu':
            if not field_value:
                return "SKIP_FIELD"
            field_value = field_value.upper()
            field_value = int(field_value)

        return field_value


    def add_outcomes(self, rule, rule_outcomes, outcomes):
        """
        Filter if labels match to a rule
        """
        # pylint: disable=too-many-nested-blocks
        rule_name = rule['name']
        outcomes.setdefault('interfaces', [])
        sub_fields = [
            'ipv4_addresses',
            'ipv6_addresses',
            'netbox_device_id',
        ]

        outcome_selection, ignored_interfaces =\
                self.get_multilist_outcomes(rule_outcomes, 'ignore_interface')

        for entry in outcome_selection:
            outcome_object = {}
            outcome_subfields_object = {}
            for key, value in entry.items():
                if isinstance(value, str):
                    value = value.strip()
                if key == 'ignore_interface':
                    continue
                if key == 'name' and value in ignored_interfaces:
                    break
                if key in sub_fields:
                    if key in ['ipv6_addresses', 'ipv4_addresses']:
                        value = value.split(',')
                        value = [x.strip() for x in value if x]
                    outcome_subfields_object[key] = {'value': value}
                else:
                    outcome_object[key] = {'value': value}
            if outcome_object:
                outcomes['interfaces'].append({'fields': outcome_object,
                                               'sub_fields': outcome_subfields_object,
                                               'by_rule': rule_name})
        return outcomes

class NetboxVirtInterfaceRule(NetboxInterfaceRule):
    """
    Subclass for caching
    """
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

            outcomes['fields'][action] = {'value': new_value}
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
        outcomes.setdefault('rules', [])
        rule_name = rule['name']
        unique_fields = {}
        custom_fields = {}
        multiply_fields = []
        for outcome in rule_outcomes:
            field_name = outcome['field_name']
            field_value = outcome['field_value']

            hostname = self.db_host.hostname

            new_value  = render_jinja(field_value, mode="nullify",
                                     HOSTNAME=hostname, **self.attributes).strip()
            if not new_value:
                continue

            if outcome['expand_value_as_list']:
                for list_value in new_value.split(','):
                    if not list_value:
                        continue
                    outcome_object = {}
                    outcome_object[field_name] = {
                            'value': list_value.strip(),
                            'use_to_identify': outcome['use_to_identify'],
                            }
                    if outcome['is_netbox_custom_field']:
                        raise ValueError('Expand Value can not be a custom Field at the same time')
                    multiply_fields.append(outcome_object)
            else:
                field_data = {
                        'value': new_value,
                        'use_to_identify': outcome['use_to_identify'],
                        'is_list': outcome['is_netbox_list_field'],
                        }
                if outcome['is_netbox_custom_field']:
                    custom_fields[field_name] = field_data
                else:
                    unique_fields[field_name] = field_data

        if multiply_fields:
            for field in multiply_fields:
                new_dict = field
                new_dict.update(unique_fields)
                outcome_object = {
                    'rule': rule_name,
                    'fields': new_dict,
                    'custom_fields': custom_fields,
                }
                outcomes['rules'].append(outcome_object)
        else:
            outcome_object = {
                'rule': rule_name,
                'fields': unique_fields,
                'custom_fields': custom_fields,
            }
            outcomes['rules'].append(outcome_object)
        return outcomes
#.
