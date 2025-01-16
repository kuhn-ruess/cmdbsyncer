#!/usr/bin/env python3
"""
Netbox Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes, import-error
from mongoengine import CASCADE
from application import db
from application.modules.rule.models import rule_types

#   .-- Rewrite Attribute
class NetboxRewriteAttributeRule(db.Document):
    """
    Rule to rewrite existing Attributes
    """
    name = db.StringField()
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview
    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type='AttributeRewriteAction'))
    render_attribute_rewrite = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
#   . -- Cluster
netbox_cluster_outcomes = [
  ('name', '* Name'),
  ('type', '* Type'),
  ('site', 'Site'),
  ('status', 'Status'),
  ('custom_field', 'Set a Custom Field key:value (Jinja)'),
  ('description', 'Description'),
]

class NetboxClusterOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    action = db.StringField(choices=netbox_cluster_outcomes)
    param = db.StringField()
    meta = {
        'strict': False,
    }

class NetboxClusterAttributes(db.Document):
    """
    Configure Clusters
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type='NetboxClusterOutcome'))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }

#.
#   . -- Virutal Machines
netbox_virtualmachines_types = [
  ('cluster', 'Cluster'),
  ('role', 'Role'),
  ('status', 'Status'),
  ('serial', 'Serial Number'),
  ('tenant', 'Tenant'),
  ('platform', 'Platform'),
  ('platform.manufacturer', 'Platform Manufacturer'),
  ('site', 'Site'),
  ('primary_ip4', 'Primary IPv4'),
  ('primary_ip6', 'Primary IPv6'),
  ('custom_field', 'Set a Custom Field key:value (Jinja)'),
]
class NetboxVirtualMachineOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    action = db.StringField(choices=netbox_virtualmachines_types)
    param = db.StringField()
    meta = {
        'strict': False,
    }

class NetboxVirtualMachineAttributes(db.Document):
    """
    Virutal Machine
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes = \
        db.ListField(field=db.EmbeddedDocumentField(document_type='NetboxVirtualMachineOutcome'))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
#   . -- Devices
netbox_outcome_types = [
  ('device_type', '* Type'),
  ('platform', 'Platform'),
  ('device_type.manufacturer', '* Device Type Manufacturer'),
  ('model', '* Model'),
  ('role', 'Role'),
  ('serial', 'Serial Number'),
  ('tenant', 'Tenant'),
  ('platform', 'Platform'),
  ('platform.manufacturer', 'Platform Manufacturer'),
  ('site', 'Site'),
  ('location', 'Location'),
  ('rack', 'Rack'),
  ('primary_ip4', 'Primary IPv4'),
  ('primary_ip6', 'Primary IPv6'),
  ('custom_field', 'Set a Custom Field key:value (Jinja)'),
  ('update_optout', 'Do never Update given Fields (comma separated list possible)'),
  ('ignore_host', 'Ignore Host(s)'),
]

class NetboxOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    action = db.StringField(choices=netbox_outcome_types)
    param = db.StringField()
    meta = {
        'strict': False,
    }

class NetboxCustomAttributes(db.Document):
    """
    Define Rule based Custom Variables
    LEGACY: This is for Devices
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type='NetboxOutcome'))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
#   . -- IP Addresses
netbox_ipam_ipaddress_outcome_types = [
  ('addresses',
   'List of IPv4 or IPv6 with Network Address '
   '(Example: 127.0.0.1/24), (Comma separated)'),
  ('family', 'Family of IP: ipv6 or ipv4'),
  ('status', 'Status of IP like: active'),
  ('assigned_object_id', 'Assigned Object ID'),
  ('assigned_object_type', 'Assigned Object Type'),
  ('vrf', "VRF"),
  ('role', 'Role'),
  ('description', 'Description'),
  ('ignore_ip', 'Ignore Rule in case of the following addresses (Comma separated)')
]

class NetboxIpamIPAddressOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    action = db.StringField(choices=netbox_ipam_ipaddress_outcome_types)
    param = db.StringField()
    use_list_variable = db.BooleanField()
    list_variable_name = db.StringField(max_length=120)

    meta = {
        'strict': False,
    }

class NetboxIpamIpaddressattributes(db.Document):
    """
    Define Rule based Custom Variables
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes =\
        db.ListField(field=db.EmbeddedDocumentField(document_type='NetboxIpamIPAddressOutcome'))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
#   . -- IPAM Prefix
netbox_prefix_outcome_types = [
  ("prefix", "Prefix eg. 172.30.180.0/24"),
  ("status", "Status like: active or decommissioning"),
  ("description", "Description"),
]

class NetboxIpamPrefixOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    action = db.StringField(choices=netbox_prefix_outcome_types)
    param = db.StringField()
    #use_list_variable = db.BooleanField()
    #list_variable_name = db.StringField(max_length=120)

    meta = {
        'strict': False,
    }

class NetboxIpamPrefixAttributes(db.Document):
    """
    Define Rule based Prefixes
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes =\
        db.ListField(field=db.EmbeddedDocumentField(document_type='NetboxIpamPrefixOutcome'))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)

    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
#   . -- Interfaces
netbox_device_interface_outcome_types = [
        ('device', '* Name of Assigned Device'),
        ('netbox_device_id', '* Numeric ID of Device'),
        ('ipv4_addresses', '* IPv4 Address list (comma seperated)'),
        ('ipv6_addresses', '* IPv6 Address list (comma seperated)'),
        ('name', '* Name'),
        ('mac_address', 'Mac Address'),
        ('description', 'Description'),
        ('type', 'Type'),
        ('admin_status', 'Admin Status'),
        ('speed', 'Speed'),
        ('duplex', 'Duplex Mode'),
        ('mode', 'Mode'),
        ('mtu', 'MTU'),
        ('ignore_interface',
                'Ignore Rule in case of the following Port/ Interface- names (Comma separated)')
]
class NetboxDcimInterfaceOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    action = db.StringField(choices=netbox_device_interface_outcome_types)
    param = db.StringField()
    use_list_variable = db.BooleanField()
    list_variable_name = db.StringField(max_length=120)
    meta = {
        'strict': False,
    }

class NetboxDcimInterfaceAttributes(db.Document):
    """
    Define Rule based Custom Variables
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes = db.ListField(field= \
            db.EmbeddedDocumentField(document_type='NetboxDcimInterfaceOutcome'))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }

netbox_virt_interface_outcome_types = [
        ('virtual_machine', '* Numeric ID of Assigned Virtual Machine'),
        ('ipv4_addresses', '* IPv4 Address list (comma seperated)'),
        ('ipv6_addresses', '* IPv6 Address list (comma seperated)'),
        ('name', '* Name'),
        ('mac_address', 'Mac Address'),
        ('description', 'Description'),
        ('type', 'Type'),
        ('admin_status', 'Admin Status'),
        ('speed', 'Speed'),
        ('duplex', 'Duplex Mode'),
        ('mode', 'Mode'),
        ('mtu', 'MTU'),
        ('ignore_interface',
                'Ignore Rule in case of the following Port/ Interface- names (Comma separated)')
]

class NetboxVirtInterfaceOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    action = db.StringField(choices=netbox_virt_interface_outcome_types)
    param = db.StringField()
    use_list_variable = db.BooleanField()
    list_variable_name = db.StringField(max_length=120)
    meta = {
        'strict': False,
    }

class NetboxVirtualizationInterfaceAttributes(db.Document):
    """
    Define Rule based Custom Variables
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes = db.ListField(field= \
            db.EmbeddedDocumentField(document_type='NetboxVirtInterfaceOutcome'))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }

#.
#   . -- Contacts
netbox_contact_outcome_types = [
    ('name', '* Name'),
    ('title', 'Title'),
    ('phone', 'Phone'),
    ('email', 'E-Mail'),
    ('address', 'Address'),
    ('description', 'Description'),
    ('group', 'Contacts Groupname'),
    ('ignore', 'Ignore matching objects for sync'),
]
class NetboxContactOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    action = db.StringField(choices=netbox_contact_outcome_types)
    param = db.StringField()
    meta = {
        'strict': False,
    }

class NetboxContactAttributes(db.Document):
    """
    Define Rule based Custom Variables
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview
    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type='NetboxContactOutcome'))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
#   . -- Dataflow
class NetboxDataflowOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    field_name = db.StringField()
    field_value = db.StringField()
    use_to_identify = db.BooleanField()
    expand_value_as_list = db.BooleanField()
    is_netbox_list_field = db.BooleanField()
    is_netbox_custom_field = db.BooleanField()
    meta = {
        'strict': False,
    }

class NetboxDataflowAttributes(db.Document):
    """
    Define Rule based DataFlow Attributes
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type='NetboxDataflowOutcome'))
    render_netbox_dataflow = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)

    def __str__(self):
        return self.name

    meta = {
        'strict': False
    }


data_flow_models = [
    ('applications', 'Applications'),
]

class NetboxDataflowModels(db.Document):
    """
    Netbox Dataflow Setttings
    """
    name = db.StringField(max_length=120)
    documentation = db.StringField()

    used_dataflow_model = db.StringField(choices=data_flow_models)
    connected_rules = db.ListField(field=\
            db.ReferenceField(document_type=NetboxDataflowAttributes,
                              reverse_delete_rule=CASCADE))

    enabled = db.BooleanField()
#.
