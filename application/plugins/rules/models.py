from application import db, app
from application.models.account import object_types
from .rule_definitions import rules as rule_names

class SyncerRuleAutomation(db.Document):
    """
    Automate Syncer Rule definition
    """
    name = db.StringField(required=True, unique=True, max_length=255)
    documentation = db.StringField()

    rule_type = db.StringField(choices=rule_names)
    rule_body = db.StringField(required=True)

    object_filter = db.StringField(choices=object_types[1:])

    enabled = db.BooleanField(default=True)

    meta = {
        'strict': False
    }

