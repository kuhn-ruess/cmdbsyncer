"""
i-doit Model
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes, import-error
from application import db
from application.modules.rule.models import rule_types

#   .-- Rewrite Attribute
class IdoitRewriteAttributeRule(db.Document):
    """
    Rule to rewrite existing Attributes
    """

    name = db.StringField()
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for preview
    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="AttributeRewriteAction"))
    render_attribute_rewrite = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.


idoit_outcome_types = [
  ('id_category', "Category Template"),
  ('id_object_type', "Define Objects Object Type"),
  ('id_object_description', "Define Attribute to use as Objects Description"),
  ('ignore_host', "Ignore host(s)"),
]

class IdoitOutcome(db.EmbeddedDocument):
    """
    i-doit Outcome
    """

    action = db.StringField(choices=idoit_outcome_types)
    param = db.StringField()
    meta = {
        'strict': False,
    }

class IdoitCustomAttributes(db.Document):
    """
    Define rule based custom i-doit variables
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="IdoitOutcome"))
    render_idoit_outcome = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)

    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
