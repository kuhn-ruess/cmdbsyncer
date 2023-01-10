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
    ('value_as_folder', "Use Value of given Attribute Name as Folder"),
    ("tag_as_folder", "Use Attribute Name of given Attribute Value as Folder"),
    ("folder_pool", "Use Pool Folder (please make sure this matches just once to a host)"),
    ("attribute", "Create Checkmk-Attribute with Syncers Attributes Value for Key given in action param"),
    ("custom_attribute", "Create Custom Checkmk Attribute: Set key:value, Placeholders: {hostname}"),
]

class CheckmkRuleOutcome(db.EmbeddedDocument):
    """
    Checkmk Export Rule Outcome


    Options
    =======

    Move Host to specified Folder
    -----------------------------
    Hardcode a custom Folder Name in _action_param_ field.

    Use Value of given Attribute Name as Folder
    -------------------------------------------
    Define an Attribute in _action_param_. The value of it, will be used
    as a Folder name for the matching host

    Use Attribute Name of given Attribute Value as Folder
    -----------------------------------------------------
    Same like the option before, but just Attribute Name and Attribute Value swapped.
    So you can pick by the attributes value.

    Use Pool Folder
    ---------------
    Please refer to the Folder Pool Documentation.

    Create Checkmk-Attribute
    ------------------------
    The given Attribute Name will be sent as Checkmk Attribute. This way you can set
    every Attribute you want like ipaddress of management board. Please refer to the documentation in
    Recipes.

    Create Custom Checkmk Attribute
    -------------------------------
    You can specify a new Attribute as key value pair, separated by double point.
    You can use {hostname} as placeholder to create for example:
    managmentboard:rib-{hostname} as new attribute

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
cmk_groups = [
 ('contact_groups', "Contact Groups"),
 ('host_groups', "Host Groups"),
 ('service_groups', "Service Groups"),
]

foreach_types = [
 ('label', "Foreach Attribute"),
 ('value', "Foreach Attribute Value")
]

class CmkGroupOutcome(db.EmbeddedDocument):
    """
    Checkmk Rule Outcome
    """
    group_name = db.StringField(choices=cmk_groups)
    foreach_type = db.StringField(choices=foreach_types)
    foreach = db.StringField(required=True)
    regex = db.StringField()

    meta = {
        'strict': False,
    }


class CheckmkGroupRule(db.Document):
    """
    Checkmk Ruleset generation
    """


    name = db.StringField(required=True, unique=True)
    outcome = db.EmbeddedDocumentField(CmkGroupOutcome)
    render_checkmk_group_outcome = db.StringField()
    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }
#.
#   .-- Checkmk Rule Mngmt


class RuleMngmtOutcome(db.EmbeddedDocument):
    """
    Checkmk Rule Managment Outcome


    Options
    =======

    Ruleset
    -------
    The needed Value can be found as "Ruleset name" within the
    Checkmk "Rule Properties" part for the needed Rule. You may need to enable
    "Show More" for the block.

    Folder
    ------
    Full path to the Checkmk Folder where the rule is to be placed.
    Use / for Main Folder

    Folder Index
    ------------
    Numeric position for the Rule in side the Folder

    Comment
    -------
    Custom Comment placed with the created rule

    Value Template
    --------------
    The Value Template need to be looked up in Checkmk.
    Create an rule as Example, then click "Export Rule for API"
    Copy the shown string and replace the needed Values with placeholders.
    Available is {{HOSTNAME}} and all other Host Attributes. It's possible to
    use the full Jinja2 Template Syntax.


    Condition Label Template
    ------------------------
    Defines which label has to match.
    Labels format is key:value. You can Hardcode something or use the same Placeholders
    like in the Value Templates (Jinja2). Only one Label can be used.
    """

    ruleset = db.StringField()
    folder = db.StringField(required=True)
    folder_index = db.IntField(default=0)
    comment = db.StringField()
    value_template = db.StringField(required=True)
    condition_label_template = db.StringField(required=True)

    meta = {
        'strict': False,
    }

class CheckmkRuleMngmt(db.Document):
    """
    Manage Checkmk Rules
    """
    name = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(FullCondition))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(db.EmbeddedDocumentField(RuleMngmtOutcome))
    render_cmk_rule_mngmt = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    meta = {
        'strict': False
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
    Rewrite all Attributes
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
