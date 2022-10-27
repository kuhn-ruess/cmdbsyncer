"""
Checkmk Ruleset Generation Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db



class CmkRulesetOutcome(db.EmbeddedDocument):
    """
    Checkmk Rule Outcome
    """
    ruleset_name = db.StringField(required=True)
    folder_attribute = db.StringField(required=True)
    folder = db.StringField(required=True)
    foreach_attribute = db.StringField(required=True)
    value_template = db.StringField(required=True)
    condition_template = db.StringField(required=True)
    meta = {
        'strict': False,
    }


class CmkRulesetRule(db.Document):
    """
    Checkmk Ruleset generation
    """


    name = db.StringField(required=True, unique=True)
    outcome = db.ListField(db.EmbeddedDocumentField(CmkRulesetOutcome))
    enabled = db.BooleanField()


    meta = {
        'strict': False,
    }
