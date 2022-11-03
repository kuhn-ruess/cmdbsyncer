"""
Model
"""
# pylint: disable=no-member, too-few-public-methods
from application import db
from application.modules.rule.models import HostCondition, CustomLabel



class CustomLabelRule(db.Document):
    """
    Rule to add Custom Labels
    """
    name = db.StringField(required=True, unique=True)
    conditions = db.ListField(db.EmbeddedDocumentField(HostCondition))
    render_host_conditions = db.StringField() # Helper for preview
    outcomes = db.ListField(db.EmbeddedDocumentField(CustomLabel))
    render_label_outcomes = db.StringField()
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
