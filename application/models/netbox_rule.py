"""
Netbox Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db
from application.models.rule import rule_types, ActionCondition, FullLabelCondition

netbox_outcome_types = [
  ('nb_device_type', "Set Device Type ID"),
  ('nb_device_role', "Set Device Role ID"),
  ('nb_tenant', "Set Device Tenant ID"),
  ('nb_platform', "Set Platform ID"),
  ('nb_site', "Set Site ID"),
  ('nb_location', "Set Location ID"),
  ('nb_rack', "Set Rack ID"),
  ('ignore_host', "Ignore Host(s)"),
]

class NetboxOutcome(db.EmbeddedDocument):
    """
    Ansible Outcome
    """
    type = db.StringField(choices=netbox_outcome_types)
    value = db.StringField()
    meta = {
        'strict': False,
    }

class NetboxCustomVariables(db.Document):
    """
    Define Rule based Custom Ansible Variables
    """

    name = db.StringField(required=True, unique=True)

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(ActionCondition))
    render_conditions = db.StringField() # Helper for preview

    outcome = db.ListField(db.EmbeddedDocumentField(NetboxOutcome))
    render_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField()
