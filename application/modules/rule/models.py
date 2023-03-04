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
    ('ewith', "String ends with (x.endswith(y)"),
    ('swith', "String starts with (x.startswith(y)"),
    ('regex', "Regex Match"),
    ('bool', "Match Bool, True or False bool(value)"),
    ('ignore', "Match All (*)"),
]

class FullCondition(db.EmbeddedDocument):
    """
    Condition

    Match Type
    ==========
    To Choice if you want to match the Hostname, or Match for Attribute you need
    to set the correct type.

    Matches
    =======

    Hostname Matches
    ----------------
    Enter the string which should match the Hostname
    Choice the correct Condition Type with it.
    If you click "Hostname Match Negate" everything will match but 
    the expression you entered


    Attribute Matches
    -----------------
    You need to enter the Attribute Key and the Attribute Value 
    together with a condition type.
    Negate will match everything not matching your expression.


    Condition Types
    ===============
    All are not case-sensitive

    String Equal
    ------------
    String need exactly match the other

    String Contains
    ---------------
    String need be part in other string

    String in list
    --------------
    String is contained in a comma separated list you provided

    String ends with
    ---------------
    String ends with the string you given

    String start swith
    -----------------
    String start with the string you given

    Regex Match
    -----------
    String need to match the given Regular Expression

    Match Bool
    ----------
    Boolean match against True or False. Please enter True oder False in the Field.

    Match All
    ---------
    Match anyway
    """
    match_type = db.StringField(choices=[('host', "Match for Hostname"),('tag', "Match for Attribute")])

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
    ('all', "All conditions must match"),
    ('any', "Any condition can match"),
    ('anyway', "Match without any condition"),
]
#.
#   .-- Filter
filter_actions = [
    ('whitelist_attribute', "Whitelist Attribute"),
    ('whitelist_attribute_value', "Whitelist Attribute with Value"),
    ('ignore_hosts', "Ignore Matching Hosts"),
]
class FilterAction(db.EmbeddedDocument):
    """
    Filter Action

    Options:
    ========

    Whitelist Attribute
    -------------------
    This attributes will be exported for the current Module.
    Match by Attribute Name

    Whitelist Attribute Value
    -------------------------
    This attributes will be exported for the current Module.
    Match by Attributes Value, not Name

    Ignore Matching Hosts
    --------------------
    A Host matching to this Rule, will never match
    """

    action = db.StringField(choices=filter_actions)
    attribute_name = db.StringField()
    meta = {
        'strict': False,
    }
#.

#   .-- Attribute Rewrite
class AttributeRewriteAction(db.EmbeddedDocument):
    """
    Old Attribute Name
    ------------------
    Name of the attribute to rewrite

    New Attribute Name
    ------------------
    New Name of the attribute
    """
    old_attribute_name = db.StringField()
    new_attribute_name = db.StringField()
    meta = {
        'strict': False
    }

#.
#   .-- Custom Attribute
class CustomAttribute(db.EmbeddedDocument):
    """
    Custom Params

    """
    attribute_name = db.StringField()
    attribute_value = db.StringField()
    meta = {
        'strict': False
    }
#.
