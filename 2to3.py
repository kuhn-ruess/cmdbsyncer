#!/usr/bin/env python3
from application import db
from application.modules.rule.models import FullCondition, CustomLabel, rule_types

#   .-- Old Helpers
host_params_types = [
    ('add_custom_label', "Add Custom Label(s)"),
    ('ignore_host', "Ignore Host(s)"),
]

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
#.
#   .-- HostRules to Custom Host Attributes
class OldHostCondition(db.EmbeddedDocument):
    """
    Host Condition
    """
    match = db.StringField(choices=condition_types)
    hostname = db.StringField(required=True)
    match_negate = db.BooleanField()
    meta = {
        'strict': False,
    }

class OldHostParams(db.EmbeddedDocument):
    """
    Custom Params
    """
    type = db.StringField(choices=host_params_types)
    name = db.StringField()
    value = db.StringField()
    meta = {
        'strict': False
    }

class HostRule(db.Document):
    """
    Host Rule to add custom Parameters for importers or exporters
    """
    name = db.StringField(required=True, unique=True)
    conditions = db.ListField(db.EmbeddedDocumentField(OldHostCondition))
    render_host_conditions = db.StringField() # Helper for preview
    params = db.ListField(db.EmbeddedDocumentField(OldHostParams))
    render_host_params = db.StringField()
    enabled = db.BooleanField()
    sort_field = db.IntField()
    meta = {
        'strict': False
    }


from application.modules.custom_attributes.models import CustomAttributeRule
if not CustomAttributeRule.objects():
    for rule in HostRule.objects():
        conditions = []
        outcomes = []
        for condition in rule.conditions:
            con = FullCondition()
            con.match_type = 'host'
            con.hostname_match = condition.match
            con.hostname = condition.hostname
            con.hostname_match_negate = condition.match_negate
            conditions.append(con)
        for param in rule.params:
            if param.type != 'add_custom_label':
                continue
            out = CustomLabel()
            out.label_name = param.name
            out.label_value = param.value
            outcomes.append(out)
        new = CustomAttributeRule()
        new.name = rule.name
        new.condition_typ = 'any'
        new.sort_field = rule.sort_field
        new.conditions = conditions
        new.outcomes = outcomes
        new.enabled = rule.enabled
        new.save()
#.
#   .-- Folder Pools
class FolderPool(db.Document):
    """
    Folder Pool
    """


    folder_name = db.StringField(required=True, unique=True)
    folder_seats = db.IntField(required=True)
    folder_seats_taken = db.IntField(default=0)

    enabled = db.BooleanField()

from application.modules.checkmk.models import CheckmkFolderPool
if not CheckmkFolderPool.objects():
    for pool in FolderPool.objects():
        new = CheckmkFolderPool()
        new.folder_name = pool.folder_name
        new.folder_seats = pool.folder_seats
        new.folder_seats_taken = pool.folder_seats_taken
        new.enabled = pool.enabled
        new.save()
#.
#   .-- Label Rules
label_choices =[('label_name', 'Label Name'), ('label_value', 'Label Value')]
class OldLabelCondition(db.EmbeddedDocument):
    """
    Condition
    """
    match_on = db.StringField(choices=label_choices)
    match = db.StringField(choices=condition_types)
    value = db.StringField(required=True)
    match_negate = db.BooleanField()
    meta = {
        'strict': False,
    }

label_outcome_types = [
    ('add', 'Add matching Labels'),
    ('remove', 'Dismiss matching Labels'),
    ('strip', 'Strip Spaces End/Begin'),
    ('lower', 'Make label lowercase'),
    ('replace', 'Replace whitespaces with _'),
    ('replace_slash', 'Replace Slahses with / (usefull if using tags/values as folder)'),
    ('replace_hyphen', 'Replace Hyphens with underscores'),
    ('replace_special', 'Replace chars like { and } which will not work as foldername'),
    ('use_value_as_attribute', 'Use Label Value as Host Attribute. Key needs to be valid'),
]

class LabelRule(db.Document):
    """
    Rule to filter Labels
    """
    name = db.StringField(required=True, unique=True)
    conditions = db.ListField(db.EmbeddedDocumentField(OldLabelCondition))
    outcome = db.ListField(db.StringField(choices=label_outcome_types))
    enabled = db.BooleanField()
    sort_field = db.IntField()
    meta = {'strict': False}

from application.modules.checkmk.models import CheckmkFilterRule
from application.modules.rule.models import FilterAction

if not CheckmkFilterRule.objects():
    for lr in LabelRule.objects():
        hit = False
        for out in lr.outcome:
            if out == 'add':
                hit = True
        if hit:
            new = CheckmkFilterRule()
            new.name = lr.name
            new.condition_typ = 'anyway'
            new.enabled = lr.enabled
            new.sort_field = lr.sort_field
            outcomes = []
            for con in lr.conditions:
                out = FilterAction() 
                out.action = 'whitelist_attribute'
                append = ""
                if con.match == 'swith':
                    append = "*"
                out.attribute_name = con.value+append
                outcomes.append(out)
            new.outcomes = outcomes
            new.save()
#.
#   .-- ActionRule
action_outcome_types = [
    ("move_folder", "Move Host to specified Folder"),
    ('value_as_folder', "Use Value of given Tag as Folder"),
    ("tag_as_folder", "Use Tag of given Value as Folder"),
    ("folder_pool", "Use Pool Folder (please make sure this matches just once to a host)"),
    ("ignore", "Deprecated: Switch to: Ignore host(s)"),
    ("ignore_host", "Ignore Host(s)"),
]
class ActionOutcome(db.EmbeddedDocument):
    """
    Outcome
    """
    type = db.StringField(choices=action_outcome_types)
    param = db.StringField()
class ActionRule(db.Document):
    """
    Rule to control Actions based on labels
    """

    name = db.StringField(required=True, unique=True)
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(FullCondition))
    render_conditions = db.StringField() # Helper for Preview

    outcome = db.ListField(db.EmbeddedDocumentField(ActionOutcome))
    render_outcome = db.StringField() # Helper for Preview

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField()

    meta = {
        'strict': False,
    }

from application.modules.checkmk.models import CheckmkRule, CheckmkRuleOutcome

if not CheckmkRule.objects():

    for rule in ActionRule.objects():
        hit = False
        for out in rule.outcome:
            if out.type in ['ignore_host', 'ignore']:
                hit = True
        if not hit:
            new = CheckmkRule()
            new.name = rule.name
            new.condition_typ = rule.condition_typ
            new.conditions = rule.conditions
            outcomes = []
            for outo in rule.outcome:
                outn = CheckmkRuleOutcome()
                outn.action = outo.type 
                outn.action_param = outo.param
                outcomes.append(outn)

            new.outcomes = outcomes
            new.last_match = rule.last_match
            new.enabled = rule.enabled
            new.sort_field = rule.sort_field
            new.save()
#.
