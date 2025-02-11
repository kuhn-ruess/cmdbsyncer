#!/usr/bin/env python3
"""
VMware Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes, import-error
from application import db
from application.modules.rule.models import rule_types

#   .-- Rewrite Attribute
class VMwareRewriteAttributes(db.Document):
    """
    Rule to rewrite existing Attributes
    """
    name = db.StringField()
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview
    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type='AttributeRewriteAction'))
    render_attribute_rewrite = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
#   . -- Custom Attributes
class VMwareCustomAttributesOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    attribute_name = db.StringField()
    attribute_value = db.StringField()
    meta = {
        'strict': False,
    }

class VMwareCustomAttributes(db.Document):
    """
    Configure Custom Attributes
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField() # Helper for preview

    outcomes = db.ListField(field=\
            db.EmbeddedDocumentField(document_type='VMwareCustomAttributesOutcome'))
    render_attribute_outcomes = db.StringField()

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }

#.
