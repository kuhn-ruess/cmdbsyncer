"""
Ansible Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db
from application.models.rule import rule_types, ActionCondition


ansible_outcome_types = [
  ('ignore', "Ignore for Ansible"),
  ('var', "Set Variable"),
]


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


class AnsibleRule(db.Document):
    """
    Ansible Rule
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


    meta = {
        'strict': False,
    }
