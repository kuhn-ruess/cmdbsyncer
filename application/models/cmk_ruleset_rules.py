"""
Checkmk Ruleset Generation Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db



class CmkRulesetOutcome(db.EmbeddedDocument):
    """
    Checkmk Rule Outcome
    """
    ruleset_name = db.StringField()
    folder_attribute = db.StringField()
    folder = db.StringField()
    foreach_attribute = db.StringField()
    value_template = db.StringField()
    condition_template = db.StringField()
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
