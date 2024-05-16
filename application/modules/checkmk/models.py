"""
Checkmk Rules
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from application import db
from application.modules.rule.models import rule_types



attriubte_sources = [
    ("cmk_inventory",  "HW/SW Inventory"),
    ("cmk_services", "Service Plugin Output"),
    ("cmk_attributes", "Attributes of Host"),
    ("cmk_labels", "Labels of Host"),
    ("cmk_service_labels", "Labels of Service"),
]

class CheckmkInventorizeAttributes(db.Document):
    """
    Attributes to be inventorized from Checkmk
    """
    attribute_names = db.StringField(required=True)
    attribute_source = db.StringField(choices=attriubte_sources)


#   .-- Checkmk Attribute Filter
class CheckmkFilterRule(db.Document):
    """
    Filter Attributes
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="FilterAction"))
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
    ("move_folder", "Move to Folder: __ Move Host to specified Folder, Jinja Support"),
    ('value_as_folder', "Deprecated: Use move_folder with Jinja"), # 2024-04-08
    ("tag_as_folder",
     "Folder by Attribute  Name: __ Use Attribute Name of given Attribute Value as Folder"),
    ("folder_pool",
     "Pool Folder: __ Use Pool Folder (please make sure this matches just once to a host)"),
    ("attribute",
     "CMK attr. by syncer attr: __ "\
     "Checkmk-Attribute with Syncers Attributes Value for Key given in action param"),
    ("custom_attribute",
     "Custom CMK Attribute. Custom: __ "\
     "Create Custom Checkmk Attribute: "\
     "Set key:value, Placeholders: {{HOSTNAME}} and all Host Attributes in Jinja Syntax"),
    ("multiple_custom_attribute","Deprecated: Just switch to normal Custom Attribute"),
    ("create_cluster",
     "Cluster: __ Create Cluster. Specify Tags with Nodes as Wildcard (*) and or Comma separated"),
    ("set_parent",
     "Parents: __ Comma Seperated list for parents, with Jinja Syntax"),
    ("dont_move",
     "Move Optout: __ Don't Move host to another Folder after inital creation"),
    ("dont_update",
     "Update Optout: __ Don't update host Attributes after initial creation"),
    ("prefix_labels",
     "Prefix Labels: __ Prefix all labels with given String"),
    ("only_update_prefixed_labels",
     "Update only Prefixed Labels: __ Only Update Labels with given prefix"),
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
    documentation = db.StringField()
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="CheckmkRuleOutcome"))
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
 ('value', "Foreach Attribute Value"),
 ('object', "Foreach Object from Account (empty for all)"),
]

class CmkGroupOutcome(db.EmbeddedDocument):
    """
    ## Group Managment Options

    ### Group Name
    You have to choose which kind of group you want to create

    ### Foreach Type

    Do you want to iterate over the Attribute Names, or Attribute Values.
    Example: if you have Attributes like: Firewall:service, DNS:service you wan't
    to use "Foreach Attribute". Is you strcture like service:Firewall, you wan't to go by Value.

    ### Foreach
    Name of the Attribute or Attribute Value we should search for.
    Use * at the  end of the String, if you wan't to match all Strings beginning with this

    ### Rewrite (optional)
    You can rewrite the groups Name with Jinja Syntax
    Leave blank if not needed. The RAW Value will be used.
    Else, use {{name}} as Placeholder for the seleted attribute.

    ### Rewrite Title (optional)
    You can rewrite the groups Title with Jinja Syntax
    Leave blank if not needed. Then Title and Name will be same.
    Otherwise use {{name}} as Placeholder for the seleted attribute.
    """
    group_name = db.StringField(choices=cmk_groups)
    foreach_type = db.StringField(choices=foreach_types)
    foreach = db.StringField(required=False)
    rewrite = db.StringField()
    rewrite_title = db.StringField()

    meta = {
        'strict': False,
    }


class CheckmkGroupRule(db.Document):
    """
    Checkmk Ruleset generation
    """


    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    outcome = db.EmbeddedDocumentField(document_type="CmkGroupOutcome")
    render_checkmk_group_outcome = db.StringField()
    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }
#.
#   .-- Checkmk Rule Mngmt


class RuleMngmtOutcome(db.EmbeddedDocument):
    """
    ### Ruleset
    The needed Value can be found as "Ruleset name" within the
    Checkmk "Rule Properties" part for the needed Rule. You may need to enable
    "Show More" for the block.

    ### Folder
    Full path to the Checkmk Folder where the rule is to be placed.
    Use / for Main Folder

    ### Folder Index
    Numeric position for the Rule in side the Folder

    ### Comment
    Custom Comment placed with the created rule

    ### Value Template
    The Value Template need to be looked up in Checkmk.
    Create an rule as Example, then click "Export Rule for API"
    Copy the shown string and replace the needed Values with placeholders.
    Available is {{HOSTNAME}} and all other Host Attributes. It's possible to
    use the full Jinja2 Template Syntax.


    ### Condition Label Template
    Defines which label has to match.
    Labels format is key:value. You can Hardcode something or use the same Placeholders
    like in the Value Templates (Jinja2). Only one Label can be used.

    ### Condition Host
    It's possible to define a Host Condition. Placeholder is {{ hostname }}
    """

    ruleset = db.StringField()
    folder = db.StringField(required=True)
    folder_index = db.IntField(default=0)
    comment = db.StringField()
    value_template = db.StringField(required=True)
    condition_label_template = db.StringField()
    condition_host = db.StringField()

    meta = {
        'strict': False,
    }

class CheckmkRuleMngmt(db.Document):
    """
    Manage Checkmk Rules
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="RuleMngmtOutcome"))
    render_cmk_rule_mngmt = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    meta = {
        'strict': False
    }

#.
#   .-- Checkmk Tag Managment

class CheckmkTagMngmt(db.Document):
    """
    Manage Checkmk Users
    """
    documentation = db.StringField()
    group_topic_name = db.StringField()
    group_title = db.StringField()
    group_id = db.StringField()
    group_help = db.StringField()
    group_multiply_by_list = db.BooleanField(default=False)
    group_multiply_list = db.StringField()


    filter_by_account = db.StringField(required=False)

    rewrite_id = db.StringField(default="{{name}}")
    rewrite_title = db.StringField(default="{{name}}")

    enabled = db.BooleanField(default=False)
    meta = {
        'strict': False
    }


#.
#   .-- Checkmk User Management
class CheckmkUserMngmt(db.Document):
    """
    Manage Checkmk Users
    """
    documentation = db.StringField()
    user_id = db.StringField()
    full_name = db.StringField()
    email = db.StringField()
    pager_address = db.StringField()

    roles = db.ListField(field=db.StringField(), default=['admin'])
    contact_groups = db.ListField(field=db.StringField(), default=['all'])

    password = db.StringField()
    overwrite_password = db.BooleanField()
    force_passwort_change = db.BooleanField()
    disable_login = db.BooleanField()
    remove_if_found = db.BooleanField()

    disabled = db.BooleanField(default=False)

#.
#   .-- Folder Pools
class CheckmkFolderPool(db.Document):
    """
    Folder Pool
    """


    documentation = db.StringField()
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
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for preview
    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="AttributeRewriteAction"))
    render_attribute_rewrite = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False
    }
#.
#   .-- Checkmk Settings

editions = [
    ('cee', "Checkmk Enterprise Edition"),
    ('cre', "Checkmk RAW Edition"),
    ('cce', "Checkmk Cloud Edition"),
    ('cme', "Checkmk MSP Edition"),

]
class CheckmkSettings(db.Document):
    """
    Checkmk Settings
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    server_user = db.StringField()
    cmk_version = db.StringField()
    cmk_edition = db.StringField(choices=editions)
    cmk_version_filename = db.StringField()
    inital_password = db.StringField()

    subscription_username = db.StringField()
    subscription_password = db.StringField()

    def __str__(self):
        """
        Self representation
        """
        return self.name
#.
#   .-- Checkmk Sites
class CheckmkSite(db.Document):
    """
    Checkmk Site
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    server_address = db.StringField(required=True, unique=True)
    settings_master = db.ReferenceField(document_type="CheckmkSettings", required=True)

    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }
#.
#   .-- Checkmk BI Aggregations

class BiAggregationOutcome(db.EmbeddedDocument):
    """
    BI Aggregation
    """
    description = db.StringField()
    rule_template = db.StringField()



class CheckmkBiAggregation(db.Document):
    """
    BI Aggregation
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="BiAggregationOutcome"))
    render_cmk_bi_rule = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    meta = {
        'strict': False
    }
#.
#   .-- Checkmk BI Rules

class BiRuleOutcome(db.EmbeddedDocument):
    """
    BI Aggregation
    """
    documentation = db.StringField()
    description = db.StringField()
    rule_template = db.StringField()

    meta = {
        'strict': False
    }


class CheckmkBiRule(db.Document):
    """
    BI Rule
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="BiRuleOutcome"))
    render_cmk_bi_rule = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    meta = {
        'strict': False
    }

#.
#   .-- Checkmk Downtimes

downtime_repeats = [
   ('', 'Use Template'),
   ('day', 'Day'),
   ('workday', 'Workday'),
   ('week', 'Week'),
   ('1.', '1. Selected Start Day of month'),
   ('2.', '2. Selected Start Day of month'),
   ('3.', '3. Selected Start Day of month'),
   ('4.', '4. Selected Start Day of month'),
   ('5.', '5. Selected Start Day of month'),
]

days = [
    ('', 'Use Template'),
    ('mon', 'Monday'),
    ('tue', 'Tuesday'),
    ('wed', 'Wednesday'),
    ('thu', 'Thursday'),
    ('fri', 'Friday'),
    ('sat', 'Saturday'),
    ('sun', 'Sunday'),
]


offsets = [
    ('', "On date"),
    ('1', "1 day later"),
    ('2', "2 day later"),
    ('3', "3 day later"),
    ('4', "4 day later"),
    ('5', "5 day later"),
    ('6', "6 day later"),
    ('7', "7 day later"),
]
class DowtimeRuleOutcome(db.EmbeddedDocument):
    """
    Checkmk Downtime
    """
    start_day = db.StringField(choices=days)
    start_day_template = db.StringField(max_length=120)
    every = db.StringField(choices=downtime_repeats)
    every_template = db.StringField(max_length=120)
    offset_days = db.StringField(choices=offsets)
    start_time_h = db.StringField()
    start_time_m = db.StringField()
    end_time_h = db.StringField()
    end_time_m = db.StringField()
    downtime_comment = db.StringField(max_length=120)
    duration_h =db.StringField()

    meta = {
        'strict': False
    }


class CheckmkDowntimeRule(db.Document):
    """
    Downtime Rule
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="DowtimeRuleOutcome"))
    render_cmk_downtime_rule = db.StringField()
    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    meta = {
        'strict': False
    }
#.
#   .-- Object Cache

class CheckmkObjectCache(db.Document):
    """
    DB Object Cache
    """

    cache_group = db.StringField()
    account = db.ReferenceField(document_type='Account')
    content = db.DictField()

    meta = {
        'strict': False
    }

#.
