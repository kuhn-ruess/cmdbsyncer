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
  ('nb_device_type', '* Type'),
  ('nb_platform', 'Platform'),
  ('nb_device_type.manufacturer', '* Manufacturer'),
  ('nb_model', '* Model'),
  ('nb_role', 'Role'),
  ('nb_serial', 'Serial Number'),
  #('nb_tenant', 'Tenant'),
  ('nb_platform', 'Platform'),
  ('nb_site', 'Site'),
  #('nb_location', 'Location'),
  #('nb_rack', 'Rack'),
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

netbox_ipam_ipaddress_outcome_types = [
  ('address', 'IPv4 or IPv6 with Network Address (Example: 127.0.0.1/24)'),
  ('family', 'Family of IP: ipv6 or ipv4'),
  ('status', 'Status of IP like: active'),
  ('assigned_object_id', 'Assigned Object ID'),
  ('assigned_object_type', 'Assigned Object Type'),
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
