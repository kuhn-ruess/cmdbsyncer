"""
Model
"""
# pylint: disable=no-member, too-few-public-methods
from application import db
from application.modules.rule.models import rule_types


class CustomAttributeRule(db.Document):
    """
    Rule to add Custom Attributes
    """
    name = db.StringField(required=True, unique=True)
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="CustomAttribute"))
    render_attribute_outcomes = db.StringField()

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
    }
