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
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for preview
    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="AttributeRewriteAction"))
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
  ('nb_device_type_sync', "Syncronise Device Type"),
  ('nb_platform_sync', "Syncronise Platform ID"),
  ('nb_primary_ip4_sync', "Sync Primary IPv4"),
  ('nb_primary_ip6_sync', "Sync Primary IPv6"),
  ('nb_device_role_sync', "Syncronise Device Role"),
  ('nb_device_role', "Set Device Role ID manualy"),
  ('nb_tenant', "Set Device Tenant ID manualy"),
  ('nb_platform', "Set Platform ID manualy"),
  ('nb_site', "Set Site ID manualy"),
  ('nb_location', "Set Location ID manualy"),
  ('nb_rack', "Set Rack ID manualy"),
  ('nb_device_type', "Set Device Type ID manualy"),
  ('update_interfaces', "Update Interfaces in Netbox"),
  ('ignore_host', "Ignore Host(s)"),
]

class NetboxOutcome(db.EmbeddedDocument):
    """
    Ansible Outcome
    """
    action = db.StringField(choices=netbox_outcome_types)
    param = db.StringField()
    meta = {
        'strict': False,
    }

class NetboxCustomAttributes(db.Document):
    """
    Define Rule based Custom Ansible Variables
    """

    name = db.StringField(required=True, unique=True)

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="NetboxOutcome"))
    render_netbox_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
