"""
Checkmk Group Generation Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db


groups = [
 ('contact_groups', "Contact Groups"),
]

class CmkGroupOutcome(db.EmbeddedDocument):
    """
    Checkmk Rule Outcome
    """
    group_name = db.StringField(choices=groups)
    foreach_label = db.StringField()
    meta = {
        'strict': False,
    }


class CmkGroupRule(db.Document):
    """
    Checkmk Ruleset generation
    """


    name = db.StringField(required=True, unique=True)
    outcome = db.ListField(db.EmbeddedDocumentField(CmkGroupOutcome))
    enabled = db.BooleanField()


    meta = {
        'strict': False,
    }
