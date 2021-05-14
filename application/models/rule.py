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


tag_condition_types = [
    ('equal', "Tag is Equal"),
    ('swith', "Tag starts with"),
    ('ewith', "Tag ends with"),

]

class ActionCondition(db.EmbeddedDocument):
    """
    Condition
    """
    tag_match = db.StringField(choices=tag_condition_types)
    tag = db.StringField(required=True)
    value_match = db.StringField(choices=condition_types)
    value = db.StringField(required=True)
    meta = {
        'strict': False,
    }

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
    conditions = db.ListField(db.EmbeddedDocumentField(ActionCondition))
    outcome = db.ListField(db.EmbeddedDocumentField(ActionOutcome))
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }

label_outcome_types = [
    ('add', 'Add matching Labels'),
    ('remove', 'Dismiss matching Labels'),
    ('strip', 'Strip Spaces End/Begin'),
    ('lower', 'Make label lowercase'),
    ('replace', 'Replace whitespaces with _'),
]

class LabelCondition(db.EmbeddedDocument):
    """
    Condition
    """
    type = db.StringField(choices=condition_types)
    value = db.StringField(required=True)

class LabelRule(db.Document):
    """
    Rule to filter Labels
    """
    name = db.StringField(required=True, unique=True)
    conditions = db.ListField(db.EmbeddedDocumentField(LabelCondition))
    outcome = db.ListField(db.StringField(choices=label_outcome_types))
    enabled = db.BooleanField()
