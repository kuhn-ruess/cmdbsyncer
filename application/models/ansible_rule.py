"""
Ansible Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db
from application.models.rule import rule_types, ActionCondition, FullLabelCondition

ansible_outcome_types = [
  ('var', "Set Variable"),
  ('ignore_host', "Ignore Host(s)"),
]

ansible_outcome_rule_types = [
  ('var', "Set Variable"),
  ('ignore_customvar', "Ignore matching Customvar"),
  ('ignore_host', "Ignore Host(s)"),
]

class AnsibleOutcomeRule(db.EmbeddedDocument):
    """
    Ansible Outcome
    """
    type = db.StringField(choices=ansible_outcome_rule_types)
    param = db.StringField()
    value = db.StringField()
    meta = {
        'strict': False,
    }

class AnsibleOutcome(db.EmbeddedDocument):
    """
    Ansible Outcome
    """
    type = db.StringField(choices=ansible_outcome_types)
    param = db.StringField()
    value = db.StringField()
    meta = {
        'strict': False,
    }

class AnsibleCustomVariables(db.Document):
    """
    Define Rule based Custom Ansible Variables
    """

    name = db.StringField(required=True, unique=True)

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(ActionCondition))
    render_conditions = db.StringField() # Helper for preview

    outcome = db.ListField(db.EmbeddedDocumentField(AnsibleOutcome))
    render_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField()

class AnsibleCustomVariablesRule(db.Document):
    """
    Rules based on Custom Varialbes (not Labels)
    """

    name = db.StringField(required=True, unique=True)

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(FullLabelCondition))
    render_conditions = db.StringField() # Helper for preview

    outcome = db.ListField(db.EmbeddedDocumentField(AnsibleOutcomeRule))
    render_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField()
