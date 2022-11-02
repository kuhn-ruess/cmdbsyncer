"""
Label Overwrite Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db
from application.models.rule import rule_types, ActionCondition

label_overwrite_outcome_types = [
  ('var', "Set Variable"),
  ('use_inventory', "Use given Inventory var (param) as label (value)"),
]

class LabelOverwriteOutcome(db.EmbeddedDocument):
    """
    Ansible Outcome
    """
    type = db.StringField(choices=label_overwrite_outcome_types)
    param = db.StringField()
    value = db.StringField()
    meta = {
        'strict': False,
    }

class LabelOverwriteRule(db.Document):
    """
    Overwrite Labels on Host with other Data
    """

    name = db.StringField(required=True, unique=True)

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(ActionCondition))
    render_conditions = db.StringField() # Helper for preview

    outcome = db.ListField(db.EmbeddedDocumentField(LabelOverwriteOutcome))
    render_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(required=True)
