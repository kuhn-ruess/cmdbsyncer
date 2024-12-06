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
#   . -- Devices
netbox_outcome_types = [
  ('device_type', '* Type'),
  ('platform', 'Platform'),
  ('device_type.manufacturer', '* Manufacturer'),
  ('model', '* Model'),
  ('role', 'Role'),
  ('serial', 'Serial Number'),
  ('tenant', 'Tenant'),
  ('platform', 'Platform'),
  ('site', 'Site'),
  ('location', 'Location'),
  ('rack', 'Rack'),
  ('primary_ip4', 'Primary IPv4'),
  #('custom_field', 'Set a Custom Field key:value (Jinja)'),
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
  ('address', 'IPv4 or IPv6 with Network Address (Example: 127.0.0.1/24)'),
  ('family', 'Family of IP: ipv6 or ipv4'),
  ('status', 'Status of IP like: active'),
  ('assigned_object_id', 'Assigned Object ID'),
  ('assigned_object_type', 'Assigned Object Type'),
  ('assigned_object_type', 'Assigned Object Type'),
  ('role', 'Role'),
  ('description', 'Description'),
  ('ignore_ip', 'Ignore matching objects for sync'),
]

class NetboxIpamIPAddressOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    action = db.StringField(choices=netbox_ipam_ipaddress_outcome_types)
    param = db.StringField()
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
#   . -- Interfaces
netbox_device_interface_outcome_types = [
        ('device', '(required) Name of Assigned Device'),
        ('netbox_device_id', '(required) Numeric ID of  Device'),
        ('ip_address', '(required) IP Address used by Interface'),
        ('name', 'Port/ Interface Name'),
        ('mac_address', 'Mac Address'),
        ('description', 'Description'),
        ('type', 'Interface Type'),
        ('admin_status', 'Admin Status'),
        ('type', 'Interface Type'),
        ('speed', 'Interface Speed'),
        ('duplex', 'Interface Duplex Mode'),
        ('description', 'Interface Description'),
        ('mac_address', 'Interface MacAddress'),
        ('mode', 'Interface Mode'),
        ('mtu', 'Interface MTU'),
        ('ignore_interface', 'Ignore matching objects for sync'),
]
class NetboxDcimInterfaceOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    action = db.StringField(choices=netbox_device_interface_outcome_types)
    param = db.StringField()
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
#.
#   . -- Contacts
netbox_contact_outcome_types = [
    ('name', 'Name (required)'),
    ('title', 'Title'),
    ('phone', 'Phone'),
    ('email', 'E-Mail'),
    ('address', 'Address'),
    ('description', 'Description'),
    ('ignore_contact', 'Ignore matching objects for sync'),
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


class NetboxDataflowModels(db.Document):
    """
    Netbox Dataflow Setttings
    """
    name = db.StringField(max_length=120)
    documentation = db.StringField()

    used_dataflow_model = db.StringField(max_length=120)
    connected_rules = db.ListField(field=\
            db.ReferenceField(document_type=NetboxDataflowAttributes,
                              reverse_delete_rule=CASCADE))

    enabled = db.BooleanField()
#.
