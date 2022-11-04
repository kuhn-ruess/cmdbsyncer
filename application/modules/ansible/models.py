"""
Ansible Rule
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db
from application.modules.rule.models import rule_types, FullLabelCondition, CustomLabel, \
                                            FilterAction, FullCondition, LabelRewriteAction

class AnsibleCustomVariablesRule(db.Document):
    """
    Rules for Ansible
    """

    name = db.StringField(required=True, unique=True)

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(FullLabelCondition))
    render_label_conditions = db.StringField() # Helper for preview

    outcomes = db.ListField(db.EmbeddedDocumentField(CustomLabel))
    render_label_outcomes = db.StringField() # Helper for preview

    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)


    meta = {
        'strict': False
    }

#   .-- Ansible Label Filter
class AnsibleFilterRule(db.Document):
    """
    Filter Attributes
    """
    name = db.StringField(required=True, unique=True)
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(FullCondition))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(db.EmbeddedDocumentField(FilterAction))
    render_filter_outcome = db.StringField()

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
    }

#.
#   .-- Rewrite Labels
class AnsibleRewriteAttributesRule(db.Document):
    """
    Rule to Attributes existing Labels
    """
    name = db.StringField()
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(FullCondition))
    render_full_conditions = db.StringField() # Helper for preview
    outcomes = db.ListField(db.EmbeddedDocumentField(LabelRewriteAction))
    render_label_rewrite = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
