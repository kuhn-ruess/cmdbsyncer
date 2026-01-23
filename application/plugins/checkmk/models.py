"""
Checkmk Rules
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
from mongoengine import DENY
from cryptography.fernet import Fernet
from application import db, app
from application.modules.rule.models import rule_types
from application.models.account import Account



attriubte_sources = [
    ("cmk_inventory",  "HW/SW Inventory"),
    ("cmk_services", "Service Plugin Output"),
    ("cmk_attributes", "Attributes of Host"),
    ("cmk_labels", "Labels of Host"),
    ("cmk_service_labels", "Labels of Service"),
]


class CheckmkHostAttribute(db.EmbeddedDocument):
    """
    Common Checkmk Host Attribute
    """
    attribute_name = db.StringField(max_length=100)
    attribute_value = db.StringField(max_length=100)


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
    ("create_folder",
    "Create a Empty Folder by Attribute: __ Do not Move the a Host in. Will not work with Objects"),
    ("folder_pool",
     "Pool Folder: __ Use Pool Folder (please make sure this matches just once to a host)"),
    ("attribute",
     "Deprecated: Migrate to Custom CMK Attribute: key:{{yourattribute}}"),
    ("custom_attribute",
     "Custom CMK Attribute. Custom: __ "\
     "Create Custom Checkmk Attribute: "\
     "Set key:value, Placeholders: {{HOSTNAME}} and all Host Attributes in Jinja Syntax"),
    ("remove_attr_if_not_set", "Remove given Attributes from Host, if not explicitly assigned"),
    ("multiple_custom_attribute","Deprecated: Just switch to normal Custom Attribute"),
    ("create_cluster",
     "Cluster: __ Create Cluster. Specify Tags with Nodes as Wildcard (*) and or Comma separated"),
    ("set_parent",
     "Parents: __ Comma Seperated list for parents, with Jinja Syntax"),
    ("dont_move",
     "Move Optout: __ Don't Move host to another Folder after inital creation"),
    ("dont_update",
     "Update Optout: __ Don't update host Attributes after initial creation"),
    ("dont_create",
     "Create Optout: __ Don't create Host if missing, but still Update it"),
    ("prefix_labels",
     "Prefix Labels: __ Prefix all labels with given String"),
    ("only_update_prefixed_labels",
     "Update only Prefixed Labels: __ Only Update Labels with given prefix"),
    ("dont_update_prefixed_labels",
     "Dont update Prefixed Labels: __ Dont Update Labels with given prefix"),
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
 ('list', "Foreach Value in List for given Attribute"),
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
    rewrite = db.StringField(default='{{name}}')
    rewrite_title = db.StringField(default='{{name}}')

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
    loop_over_list = db.BooleanField(default=False)
    list_to_loop = db.StringField()
    value_template = db.StringField(required=True)
    condition_label_template = db.StringField()
    condition_host = db.StringField()
    condition_service = db.StringField()
    condition_service_label = db.StringField()

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
    Manage Checkmk Tags
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
    force_password_change = db.BooleanField()
    disable_login = db.BooleanField()
    remove_if_found = db.BooleanField()

    disabled = db.BooleanField(default=False)

    meta = {
        'strict': False
    }

#.
#   .-- Folder Pools
class CheckmkFolderPool(db.Document):
    """
    Folder Pool
    """


    documentation = db.StringField()
    folder_name = db.StringField(required=True, unique=True, max_length=255)
    folder_title = db.StringField(max_length=255)
    folder_seats = db.IntField(required=True)
    folder_seats_taken = db.IntField(default=0)

    assigned_site_id = db.StringField(max_length=255)

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

    webserver_certificate = db.StringField()
    webserver_certificate_private_key = db.StringField()
    webserver_certificate_intermediate = db.StringField()


    meta = {
        'strict': False
    }

    def __str__(self):
        """
        Self representation
        """
        return self.name
#.
#   .-- Checkmk Sites


class AnsibleVariable(db.EmbeddedDocument):
    """
    Ansible Variable
    """
    variable_name = db.StringField(required=True, max_length=160)
    variable_value = db.StringField(required=True, max_length=160)

class CheckmkSite(db.Document):
    """
    Checkmk Site
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    server_address = db.StringField(required=True)
    settings_master = db.ReferenceField(document_type="CheckmkSettings", required=True)


    custom_ansible_variables = \
            db.ListField(field=db.EmbeddedDocumentField(document_type="AnsibleVariable"))

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
#   .-- Checkmk Passwords
class CheckmkPassword(db.Document):
    """
    Checkmk Passwords
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    title = db.StringField(required=True)
    comment = db.StringField()
    documentation_url = db.StringField()
    password_crypted = db.StringField()
    owner = db.StringField(default="admin", required=True)
    shared = db.ListField(field=db.StringField())

    def set_password(self, password):
        """
        Encryp Password
        """
        f = Fernet(app.config['CRYPTOGRAPHY_KEY'])
        self.password_crypted = f.encrypt(str.encode(password)).decode('utf-8')


    def get_password(self):
        """
        Decrypt Password
        """
        f = Fernet(app.config['CRYPTOGRAPHY_KEY'])
        return f.decrypt(str.encode(self.password_crypted)).decode('utf-8')


    enabled = db.BooleanField()
#.
#   .-- Checkmk DCD Rules


class DCDCreationRule(db.EmbeddedDocument):
    """
    DCD Creation Rule
    """
    folder_path = db.StringField(max_length=100)
    host_attributes = \
            db.ListField(field=db.EmbeddedDocumentField(document_type="CheckmkHostAttribute"))
    delete_hosts = db.BooleanField()
    host_filters = db.ListField(field=db.StringField(max_length=100))


class DCDTimerange(db.EmbeddedDocument):
    """
    DCD Timerange
    """
    start_hour = db.IntField()
    start_minute = db.IntField()
    end_hour = db.IntField()
    end_minute = db.IntField()


class DCDRuleOutcome(db.EmbeddedDocument):
    """
    DCD Rule Outcome
    """
    dcd_id = db.StringField(required=True, max_length=100)
    title = db.StringField(required=True, max_length=100)
    comment = db.StringField()
    documentation_url = db.StringField(max_length=100)
    disabled = db.BooleanField(default=False)
    site = db.StringField(required=True, max_length=100)
    connector_type = db.StringField(required=True, default="piggyback", max_length=100)
    restricted_source_hosts = db.ListField(field=db.StringField(max_length=100))
    interval = db.IntField(default=60)
    creation_rules = db.ListField(field=db.EmbeddedDocumentField(document_type="DCDCreationRule"))
    activate_changes_interval = db.IntField(required=True, default=600)
    discover_on_creation = db.BooleanField()
    exclude_time_ranges = db.ListField(field=db.EmbeddedDocumentField(document_type="DCDTimerange"))
    no_deletion_time_after_init = db.IntField(default=6000, required=True)
    max_cache_age = db.IntField(default=3600, required=True)
    validity_period = db.IntField(default=60, required=True)

    meta = {
        'strict': False
    }


class CheckmkDCDRule(db.Document):
    """
    DCD Rule
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="DCDRuleOutcome"))
    render_cmk_dcd_rule = db.StringField()
    last_match = db.BooleanField(default=False)


    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)

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
   ('once', 'Only Once'),
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
    ('today', "Today"),
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
    offset_days_template = db.StringField()
    start_time_h = db.StringField(max_length=255, default=0)
    start_time_m = db.StringField(max_length=255, default=0)
    end_time_h = db.StringField(max_length=255, default=0)
    end_time_m = db.StringField(max_length=255, default=0)
    downtime_comment = db.StringField(max_length=120, required=True)
    duration_h =db.StringField(max_length=255)

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
    account = db.ReferenceField(document_type=Account, reverse_delete_rule=DENY)
    content = db.DictField()

    meta = {
        'strict': False
    }

#.
