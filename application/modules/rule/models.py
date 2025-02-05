"""
Default Rule Models
"""
# pylint: disable=no-member, too-few-public-methods
from application import db


#   .-- Condition Types
# IMPORTANT: Always also add in Views if new condition types
condition_types = [
    ('equal', "String Equal (x == y)"),
    ('in', "String contains String (in)"),
    ('not_in', "String not contains String (not in)"),
    ('in_list', "Hosts Attribute equals a String in given comma separated list"),
    ('string_in_list', "String included in Attributes (Python) List"),
    ('ewith', "String ends with (x.endswith(y)"),
    ('swith', "String starts with (x.startswith(y)"),
    ('regex', "Regex Match"),
    ('bool', "Match Bool, True or False bool(value)"),
    ('ignore', "Match All (*) (Negate for Not exist)"),
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

    Match All (Negate for: Does not Exist)
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
    ('whitelist_attribute', "Whitelist Attribute (Use e.g. NAME* for everyhing starting with NAME)"),
    ('whitelist_attribute_value', "Whitelist Attribute with Value (Use of Wildcard like in Attribute with *)"),
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
    Match by Attribute Name. Use * at the end of attribute to match startswith

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

modes_name = [
  ("", "Don't Use (Set  old attribute if you want to create a new custom attribute)"),
  ("string", "Overwrite with a fixed String"),
  ("jinja",
     "Overwrite with Jinja Template and access to all Hosts Attributes, including {{HOSTNAME}}"),
  ("convert_list", "Convert List of String to single Attributes and give them the below set value"),
]

modes_value = [
  ("", "Don't Use"),
  ("string", "To String"),
  ("split", "With Split, Syntax: SEPERATOR:INDEX"),
  ("jinja", "With Jinja Template and access to all Hosts Attributes, including {{HOSTNAME}}"),
]
class AttributeRewriteAction(db.EmbeddedDocument):
    """
    Attribute rewrite
    """
    overwrite_name = db.StringField(choices=modes_name, default='string')
    old_attribute_name = db.StringField()
    new_attribute_name = db.StringField()

    overwrite_value = db.StringField(choices=modes_value, default="None")
    new_value = db.StringField()
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
    #sensitive_value = db.BooleanField(default=False)
    meta = {
        'strict': False
    }
#.
