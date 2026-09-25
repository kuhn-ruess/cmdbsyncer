"""
Default Rule Models
"""
# pylint: disable=too-few-public-methods
from application import db
from application.modules.rule.match import AGE_CONDITIONS


#   .-- Condition Types
# IMPORTANT: Always also add in Views if new condition types
condition_types = [
    ('equal', "Exact Match - Attribute exactly equals the given value"),
    ('in', "Contains - Is the given string contained in the attribute?"
           " (works with strings, JSON/Python lists)"),
    ('not_in', "Not Contains - Is the given string NOT contained in the attribute?"
               " (works with strings, JSON/Python lists)"),
    ('in_list', "Value in List - Is the attribute value found in your comma-separated list?"
                " (e.g., 'server1,server2,server3')"),
    ('string_in_list', "String in Python List - Is your string found in the attribute's"
                       " Python list? (auto-converts comma-separated strings to lists)"),
    ('ewith', "Ends With - Does the attribute end with your string?"),
    ('swith', "Starts With - Does the attribute start with your string?"),
    ('regex', "Regular Expression - Does the attribute match your regex pattern?"),
    ('bool', "Boolean Match - Does the attribute match your True/False value?"),
    ('older_than', "Older Than - Is the attribute a timestamp older than the given age?"
                   " (e.g. '2d', '12h', '30m', '1w', or a plain number of days)"),
    ('newer_than', "Newer Than - Is the attribute a timestamp not older than the given age?"
                   " (same notation as Older Than)"),
    ('ignore', "Always Match - Matches everything (use negate to check 'does not exist')"),
]

# The age conditions read their operand as a point in time. Only the value of
# an attribute can be one: a hostname and an attribute name are names, so an
# age condition there can never be true — and, negated, would always be true
# and turn the condition into a silent catch-all. They are therefore offered
# for the attribute value only.
name_condition_types = [x for x in condition_types if x[0] not in AGE_CONDITIONS]


class FullCondition(db.EmbeddedDocument):
    r"""
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


    Condition Types (All are case-insensitive except regex)
    =============================================================

    Exact Match
    -----------
    Attribute must exactly equal your value.
    Example: hostname = "webserver01" matches "webserver01"

    Contains
    --------
    Your string is contained anywhere in the attribute.
    Works with strings and JSON/Python lists.
    Example: "web" matches hostname "webserver01" or ["webserver01", "dbserver"]

    Not Contains
    ------------
    Your string is NOT found in the attribute.
    Works with strings and JSON/Python lists.
    Example: "db" does not match hostname "webserver01" or ["web01", "web02"]

    Value in List
    -------------
    Check if the attribute value exists in your comma-separated list.
    Example: Host has hostname="web01", your list="web01,web02,db01" → Matches
    Use case: Check if server is in a specific list of allowed servers

    String in Python List  
    --------------------
    Check if your string exists in the attribute's Python list.
    Works with both actual Python lists and comma-separated string attributes.
    Example: Attribute=['app1','app2'] or "app1,app2", your string="app1" → Matches
    Use case: Check if a service is installed on the server

    Ends With
    ---------
    Attribute ends with your string.
    Example: hostname ending with ".prod" for production servers

    Starts With
    -----------
    Attribute starts with your string.
    Example: hostname starting with "web-" for web servers

    Regular Expression
    -----------------
    Attribute matches your regex pattern (case-sensitive).
    Example: "^web-\d+\.prod$" matches "web-01.prod"

    Boolean Match
    -------------
    Attribute matches your True/False value.
    Accepts: true, false, True, False, none, None, empty values
    Example: Check if maintenance_mode is True

    Older Than / Newer Than
    -----------------------
    Offered for "Value Match" only: the attribute's value is read as a
    point in time and compared against the clock, not against your text.
    A hostname and an attribute name are names, never a point in time,
    so "Hostname Match" and "Tag Match" do not offer these two.
    Enter an age: a number followed by
    m (minutes), h (hours), d (days) or w (weeks) — a number on its own
    counts days.
    Example: Attribute Key syncer_last_seen, Value Match "Older Than",
    Value "2d" matches every host that was not seen for more than two days.
    Use case: switch a host off once it stopped being imported, and back on
    with "Newer Than" as soon as it is seen again.
    An attribute that is not a point in time never matches, in either
    direction — a host without a sighting date falls through both rules.
    Careful with negate: "not older than 2d" also matches the hosts that
    have no date at all, while "Newer Than 2d" does not.

    Always Match (Ignore)
    --------------------
    Always matches (useful for catch-all rules).
    When negated: Only matches if the attribute does NOT exist.
    """
    match_type = db.StringField(choices=[
        ('host', "Match for Hostname"),
        ('tag', "Match for Attribute"),
    ])

    hostname_match = db.StringField(choices=name_condition_types)
    hostname = db.StringField()
    hostname_match_negate = db.BooleanField()

    tag_match = db.StringField(choices=name_condition_types)
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
    ('whitelist_attribute',
        "Whitelist Attribute (Use e.g. NAME* for everyhing starting with NAME)"),
    ('whitelist_attribute_value',
        "Whitelist Attribute with Value (Use of Wildcard like in Attribute with *)"),
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
