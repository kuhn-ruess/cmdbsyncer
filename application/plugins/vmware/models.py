#!/usr/bin/env python3
"""
VMware Rule
"""
# pylint: disable=too-few-public-methods
from application import db
from application.modules.rule.models import (
    ListSourceMixin, RewriteRuleFields, list_source_fields,
    condition_fields, outcome_fields, rule_state_fields,
)

#   .-- Rewrite Attribute
class VMwareRewriteAttributes(RewriteRuleFields, db.Document):
    """
    Rule to rewrite existing Attributes
    """
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

class VMwareCustomAttributes(ListSourceMixin, db.Document):
    """
    Configure Custom Attributes
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    # Per host or from a pasted list, see ``list_source_fields``.
    rule_source, list_source = list_source_fields()

    condition_typ, conditions, render_full_conditions = condition_fields()

    outcomes, render_attribute_outcomes = outcome_fields('VMwareCustomAttributesOutcome')

    last_match, enabled, sort_field = rule_state_fields()
    meta = {
        'strict': False
    }

#.
