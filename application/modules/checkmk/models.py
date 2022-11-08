"""
Checkmk Rules
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db
from application.modules.rule.models import rule_types, FullCondition, FilterAction, \
                                            AttributeRewriteAction

#   .-- Checkmk Attribute Filter
class CheckmkFilterRule(db.Document):
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

#   .-- Checkmk Actions
action_outcome_types = [
    ("move_folder", "Move Host to specified Folder"),
    ('value_as_folder', "Use Attribute of given Tag as Folder"),
    ("tag_as_folder", "Use Tag of given Attribute as Folder"),
    ("folder_pool", "Use Pool Folder (please make sure this matches just once to a host)"),
    ("attribute", "Create Checkmk Attribute with Attribute given in action param"),
]

class CheckmkRuleOutcome(db.EmbeddedDocument):
    """
    Checkmk Rule Outcome
    """
    action = db.StringField(choices=action_outcome_types)
    action_param = db.StringField()
    meta = {
        'strict': False,
    }

class CheckmkRule(db.Document):
    """
    Checkmk Actions
    """
    name = db.StringField(required=True, unique=True)
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(FullCondition))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(db.EmbeddedDocumentField(CheckmkRuleOutcome))
    render_checkmk_outcome = db.StringField()

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
    }

#.
#   .-- Checkmk Groups
groups = [
 ('contact_groups', "Contact Groups"),
 ('host_groups', "Host Groups"),
 ('service_groups', "Service Groups"),
]

foreach_types = [
 ('label', "Foreach Attribute name for given Value"),
 ('value', "Foreach Value for given Attribute name")
]

class CmkGroupOutcome(db.EmbeddedDocument):
    """
    Checkmk Rule Outcome
    """
    group_name = db.StringField(choices=groups)
    foreach_type = db.StringField(choices=foreach_types)
    foreach = db.StringField()
    regex = db.StringField()
    meta = {
        'strict': False,
    }


class CheckmkGroupRule(db.Document):
    """
    Checkmk Ruleset generation
    """


    name = db.StringField(required=True, unique=True)
    outcomes = db.ListField(db.EmbeddedDocumentField(CmkGroupOutcome))
    render_checkmk_group_outcome = db.StringField()
    enabled = db.BooleanField()


    meta = {
        'strict': False,
    }
#.
#   .-- Folder Pools
class CheckmkFolderPool(db.Document):
    """
    Folder Pool
    """


    folder_name = db.StringField(required=True, unique=True)
    folder_seats = db.IntField(required=True)
    folder_seats_taken = db.IntField(default=0)

    enabled = db.BooleanField()


    meta = {
        'strict': False,
    }

    def has_free_seat(self):
        """
        Check if the Pool has a free Seat
        """
        if self.folder_seats_taken < self.folder_seats:
            return True
        return False
#.
#   .-- Rewrite Attributes
class CheckmkRewriteAttributeRule(db.Document):
    """
    Rule to rewrite existing Attributes
    """
    name = db.StringField()
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(FullCondition))
    render_full_conditions = db.StringField() # Helper for preview
    outcomes = db.ListField(db.EmbeddedDocumentField(AttributeRewriteAction))
    render_attribute_rewrite = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
