"""
Ansible Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db
from application.models.rule import condition_types, rule_types


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


class AnsibleCondition(db.EmbeddedDocument):
    """
    Condition
    """
    match_type = db.StringField(choices=[('host', "Match for Hostname"),('tag', "Match for Tag")])

    hostname_match = db.StringField(choices=condition_types)
    hostname = db.StringField()
    hostname_match_negate = db.BooleanField()

    tag_match = db.StringField(choices=condition_types)
    tag = db.StringField()
    tag_match_negate = db.BooleanField()

    value_match = db.StringField(choices=condition_types)
    value = db.StringField()
    value_match_negate = db.BooleanField()
    meta = {
        'strict': False,
    }


class AnsibleRule(db.Document):
    """
    Ansible Rule
    """


    name = db.StringField(required=True, unique=True)

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(AnsibleCondition))
    outcome = db.ListField(db.EmbeddedDocumentField(AnsibleOutcome))
    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField()


    meta = {
        'strict': False,
    }
