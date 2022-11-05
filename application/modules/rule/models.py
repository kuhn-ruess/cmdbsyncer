"""
Default Rule Models
"""
# pylint: disable=no-member, too-few-public-methods
from application import db


#   .-- Condition Types
condition_types = [
    ('equal', "String Equal (x == y)"),
    ('in', "String Contains (in)"),
    ('in_list', "String in list (comma seperated) (x in [y,y,y])"),
    ('ewith', "String Endswith (x.endswith(y)"),
    ('swith', "String Startswith (x.startswith(y)"),
    ('regex', "Regex Match (can cause performance problems)"),
    ('bool', "Match Bool, True or False bool(value)"),
    ('ignore', "Match All (*)"),
]

class FullCondition(db.EmbeddedDocument):
    """
    Condition
    """
    match_type = db.StringField(choices=[('host', "Match for Hostname"),('tag', "Match for Label")])

    hostname_match = db.StringField(choices=condition_types)
    hostname = db.StringField()
    hostname_match_negate = db.BooleanField()

    tag_match = db.StringField(choices=condition_types)
    tag = db.StringField()
    tag_match_negate = db.BooleanField()

    value_match = db.StringField(choices=condition_types)
    value = db.StringField()
    value_match_negate = db.BooleanField()


    meta = {
        'strict': False,
    }

#.
#   .-- Action Rules
rule_types = [
    ('anyway', "Match without any condition"),
    ('any', "Any condition can match"),
    ('all', "All conditions must match"),
]
#.
#   .-- Filter
filter_actions = [
    ('whitelist_attribute', "Whitelist Label/ Inventory Attribute"),
    ('ignore_hosts', "Ignore Matching Hosts"),
]
class FilterAction(db.EmbeddedDocument):
    """
    Filter Action
    """
    action = db.StringField(choices=filter_actions)
    attribute_name = db.StringField()
    meta = {
        'strict': False,
    }
#.

#   .-- Label Rewrite
class LabelRewriteAction(db.EmbeddedDocument):
    """
    Custom Params
    """
    old_label_name = db.StringField()
    new_label_name = db.StringField()
    meta = {
        'strict': False
    }

#.
#   .-- Custom Label
class CustomLabel(db.EmbeddedDocument):
    """
    Custom Params
    """
    label_name = db.StringField()
    label_value = db.StringField()
    meta = {
        'strict': False
    }
#.
