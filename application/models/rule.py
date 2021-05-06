"""
Rule
"""
# pylint: disable=no-member, too-few-public-methods
from application import db


rule_types = [
    ('all', "All conditions must mach"),
    ('any', "Any condition can mach"),
]

condition_types = [
    ('equal', "Equal"),
    ('not_equal', "Not equal"),
    ('in', "Contains"),
]

action_outcome_types = [
    ("move_folder", "Move Host to given Folder"),
    ("ignore", "Ignore this host"),
]


class Condition(db.EmbeddedDocument):
    """
    Condition
    """
    tag = db.StringField(required=True)
    type = db.StringField(choices=condition_types)
    value = db.StringField(required=True)

class ActionOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    type = db.StringField(choices=action_outcome_types)
    param = db.StringField()

class ActionRule(db.Document):
    """
    Rule to control Actions based on labels
    """

    name = db.StringField(required=True, unique=True)
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(Condition))
    outcome = db.ListField(db.EmbeddedDocumentField(ActionOutcome))
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }

label_outcome_types = [
    ('add', 'Add matching Labels')
]

class LabelRule(db.Document):
    """
    Rule to filter Labels
    """
    name = db.StringField(required=True, unique=True)
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(Condition))
    outcome = db.StringField(choices=label_outcome_types)
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
