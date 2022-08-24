"""
Rule
"""
# pylint: disable=no-member, too-few-public-methods
from application import db


rule_types = [
    ('all', "All conditions must match"),
    ('any', "Any condition can match"),
    ('anyway', "Match without any condition"),
]

condition_types = [
    ('equal', "String Equal"),
    ('in', "String Contains"),
    ('in_list', "String in list (comma seperated)"),
    ('ewith', "String Endswith"),
    ('swith', "String Startswith"),
    ('regex', "Regex Match (can cause performance problems)"),
    ('ignore', "Match All"),
]

action_outcome_types = [
    ("move_folder", "Move Host to specified Folder"),
    ('value_as_folder', "Use Value of given Tag as Folder"),
    ("tag_as_folder", "Use Tag of given Value as Folder"),
    ("ignore", "Ignore this host"),
    ("folder_pool", "Use Pool Folder (please make sure this matches just once to a host)"),
]


host_params_types = [
    ('ignore_hosts', "Ignore matching Hosts"),
    ('add_custom_label', "Add Custom Label (use name and value)"),
]


class ActionCondition(db.EmbeddedDocument):
    """
    Condition
    """
    match_type = db.StringField(choices=[('host', "Match for Hostname"),('tag', "Match for Tag")])

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
    conditions = db.ListField(db.EmbeddedDocumentField(ActionCondition))
    render_conditions = db.StringField()

    outcome = db.ListField(db.EmbeddedDocumentField(ActionOutcome))
    render_outcome = db.StringField()

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField()

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

class LabelCondition(db.EmbeddedDocument):
    """
    Condition
    """
    match_on = db.StringField(choices=[('label_name', 'Label Name'),
                                       ('label_value', 'Label Value')])
    match = db.StringField(choices=condition_types)
    value = db.StringField(required=True)
    match_negate = db.BooleanField()
    meta = {
        'strict': False,
    }


class LabelRule(db.Document):
    """
    Rule to filter Labels
    """
    name = db.StringField(required=True, unique=True)
    conditions = db.ListField(db.EmbeddedDocumentField(LabelCondition))
    render_label_conditions = db.StringField()
    outcome = db.ListField(db.StringField(choices=label_outcome_types))
    enabled = db.BooleanField()
    sort_field = db.IntField()

class HostCondition(db.EmbeddedDocument):
    """
    Host Condition
    """
    match = db.StringField(choices=condition_types)
    hostname = db.StringField(required=True)
    match_negate = db.BooleanField()
    meta = {
        'strict': False,
    }

class HostParams(db.EmbeddedDocument):
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
    conditions = db.ListField(db.EmbeddedDocumentField(HostCondition))
    render_host_conditions = db.StringField()
    params = db.ListField(db.EmbeddedDocumentField(HostParams))
    render_host_params = db.StringField()
    enabled = db.BooleanField()
    target = db.StringField(choices=[('import', 'Import'),('export', 'Export')])
    sort_field = db.IntField()
    meta = {
        'strict': False
    }
