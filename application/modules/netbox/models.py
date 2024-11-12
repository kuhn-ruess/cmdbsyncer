"""
Netbox Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes, import-error
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

# About the Names:
# If they not end with _sync, their value is used as content
# for the request
# if they end with sync, they sync with an netbox endpoint

netbox_outcome_types = [
  ('nb_device_type_sync', 'Syncronise Device Type'),
  ('nb_platform_sync', 'Syncronise Platform ID'),
  ('sub_manufacturer_sync', 'Syncronise Manufacturer for Device Type'),
  ('nb_role_sync', 'Syncronise (Device) Role'),
  ('nb_role', 'Set (Device) Role ID manually'),
  ('nb_tenant', 'Set Device Tenant ID manually'),
  ('nb_platform', 'Set Platform ID manually'),
  ('nb_site', 'Set Site ID manually'),
  ('nb_location', 'Set Location ID manually'),
  ('nb_rack', 'Set Rack ID manually'),
  ('nb_device_type', 'Set Device Type ID manually'),
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

netbox_ipam_ipaddress_outcome_types = [
  ('ip_address', 'IPv4 or IPv6 with Network Address (Example: 127.0.0.1/24)'),
  ('ip_family', 'Family of IP: ipv6 or ipv4'),
  ('assigned', 'Is Assigned (bool)'),
  ('assigned_obj_id', 'Assigned Object ID'),
  ('assigned_obj_type', 'Assigned Object Type'),
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

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type='NetboxIpamIPAddressOutcome'))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }

netbox_device_interface_outcome_types = [
        ('device', '(required) ID of Assigned Device'),
        ('ip_address', '(required) IP Address used by Interface'),
        ('portName', 'Port Name'),
        ('macAddress', 'Mac Address'),
        ('description', 'Description'),
        ('interfaceType', 'Interface Type'),
        ('adminStatus', 'Admin Status'),
        ('type', 'Interface Type'),
        ('speed', 'Interface Speed'),
        ('duplex', 'Interface Duplex Mode'),
        ('description', 'Interface Description'),
        ('macAddress', 'Interface MacAddress'),
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

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type='NetboxDcimInterfaceOutcome'))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }

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
