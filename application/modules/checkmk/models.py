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
    ("custom_attribute", "Create Custom Checkmk Attribute: Set key:value, Placeholders: {{HOSTNAME}} and all Host Attributes in Jinja Syntax"),
    ("create_cluster", "Create Cluster. Specify Tags with Nodes as Wildcard (*) and or Comma separated"),
    ("dont_move", "Don't Move host to another Folder after inital creation"),
]

class CheckmkRuleOutcome(db.EmbeddedDocument):
    """
    ### Move Host to specified Folder

    Hardcode a custom Folder Name in _action_param_ field.

    ### Use Value of given Attribute Name as Folder

    Define an Attribute in _action_param_. The value of it, will be used
    as a Folder name for the matching host

    ### Use Attribute Name of given Attribute Value as Folder

    Same like the option before, but just Attribute Name and Attribute Value swapped.
    So you can pick by the attributes value.

    ### Use Pool Folder

    Matching Host will use a Pool Folder. If not action_param is given,
    the system will query from all folders. Otherwise you can provide a comma seperated list
    of Folder Pool Names.
    For more Details, please refer to the [Folder Pool Documentation](folder_pools.md).

    ### Create Checkmk-Attribute

    The given Attribute Name will be sent as Checkmk Attribute. This way you can set
    every Attribute you want like ipaddress of management board. Please refer to the [documentation in
    Recipes](cmk_attributes.md).

    ### Create Custom Checkmk Attribute

    You can specify a new Attribute as key value pair, separated by double point.
    You can use {{hostname}} as placeholder to create for example:
    managmentboard:rib-{{hostname}} as new attribute

    ### Create Cluster
    The Matching Host will be created as a Cluster in Checkmk.
    Since Cluster have Nodes, you need to tell syncer in witch attribute he will find
    their Names. You can add the Attributes comma seperated, and use * as Wildcard add the
    end of the Name. See also the [Documentation](create_cluster.md).


    ### Don't Move hosts
    Host will be created matching the Folder Rules, but not moved anymore.
    When something changes like Data in the CMDB, or he is moved manual in WATO,
    the move operation is skipped on export.
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
#   .-- Checkmk User Management
class CheckmkUserMngmt(db.Document):
    """
    Manage Checkmk Users
    """
    user_id = db.StringField()
    full_name = db.StringField()
    email = db.StringField()
    pager_address = db.StringField()

    roles = db.ListField(db.StringField(), default=['admin'])
    contact_groups = db.ListField(db.StringField(), default=['all'])

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
    server_address = db.StringField(required=True, unique=True)
    settings_master = db.ReferenceField(CheckmkSettings, required=True)

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

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(FullCondition))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(db.EmbeddedDocumentField(BiAggregationOutcome))
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

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(db.EmbeddedDocumentField(FullCondition))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(db.EmbeddedDocumentField(BiRuleOutcome))
    render_cmk_bi_rule = db.StringField()
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
    account = db.ReferenceField('Account')
    content = db.DictField()

    meta = {
        'strict': False
    }

#.
