"""
i-doit Model
"""
# pylint: disable=too-few-public-methods
from application import db
from application.modules.rule.models import (
    ListSourceMixin, RewriteRuleFields, list_source_fields,
    condition_fields, outcome_fields, rule_state_fields,
)

#   .-- Rewrite Attribute
class IdoitRewriteAttributeRule(RewriteRuleFields, db.Document):
    """
    Rule to rewrite existing Attributes
    """

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

class IdoitCustomAttributes(ListSourceMixin, db.Document):
    """
    Define rule based custom i-doit variables
    """

    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    # Per host or from a pasted list, see ``list_source_fields``.
    rule_source, list_source = list_source_fields()

    condition_typ, conditions, render_full_conditions = condition_fields()

    outcomes, render_idoit_outcome = outcome_fields('IdoitOutcome')

    last_match, enabled, sort_field = rule_state_fields()
    meta = {
        'strict': False
    }
