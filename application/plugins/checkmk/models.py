"""
Checkmk Rules
"""
# Mongoengine Document classes are data carriers; they don't need
# additional public methods to satisfy pylint.
# pylint: disable=too-few-public-methods
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
# Warning shown for actions that are on their way out.
DEPRECATION_WARNING = "will removed with 4.4"

# Single source of truth for the outcome actions, grouped into categories and
# carrying a short name, a human description and an optional parameter hint.
# The card picker on the rule form (see admin/model/_action_picker.html) renders
# from this; ``action_outcome_types`` and ``DEPRECATED_ACTIONS`` are derived
# from it so there is only one list to maintain.
#   value      - stored on the outcome
#   name       - short label shown on the card and in the outcome summary
#   desc       - one-line explanation of what the action does
#   param      - placeholder/hint for the action's parameter field ('' = none)
#   deprecated - True keeps the action for legacy rules but blocks new use
ACTION_CATALOG = [
    {
        "group": "Folder placement",
        "actions": [
            {"value": "move_folder", "name": "Move to Folder",
             "desc": "Move the host into the folder you specify.",
             "param": "Folder path, e.g. linux/{{os}}"},
            {"value": "tag_as_folder", "name": "Folder by Attribute Name",
             "desc": "Use the attribute name of the given attribute value as folder.",
             "param": "Attribute name"},
            {"value": "create_folder", "name": "Create Empty Folder",
             "desc": "Create an empty folder by attribute without moving the host "
                     "in. Does not work with objects.",
             "param": "Attribute name"},
        ],
    },
    {
        "group": "Pools",
        "actions": [
            {"value": "folder_pool", "name": "Pool Folder",
             "desc": "Use a pool folder (make sure this matches a host only once).",
             "param": ""},
            {"value": "site_pool", "name": "Site Pool",
             "desc": "Spread the host across the sites of a site pool for load "
                     "balancing. Picks the least-loaded site and stays sticky: the "
                     "host keeps its site once assigned.",
             "param": "Site pool name (Jinja allowed)"},
        ],
    },
    {
        "group": "Attributes",
        "actions": [
            {"value": "custom_attribute", "name": "Custom Checkmk Attribute",
             "desc": "Create a custom Checkmk attribute in key:value form.",
             "param": "key:value"},
            {"value": "remove_attr_if_not_set", "name": "Remove Attribute if unset",
             "desc": "Remove the given attributes from the host if not explicitly set.",
             "param": "Attribute name(s)"},
        ],
    },
    {
        "group": "Built-in Attributes",
        "actions": [
            {"value": "set_ip_address_family", "name": "IP Address Family",
             "desc": "Set the host's IP address family — e.g. no-ip for a host "
                     "monitored without an IP.",
             "param": "Pick a value", "attr": "tag_address_family",
             "values": ["ip-v4-only", "ip-v6-only", "ip-v4v6", "no-ip"]},
            {"value": "set_ipaddress", "name": "IPv4 Address",
             "desc": "Set the host's IPv4 address.",
             "param": "e.g. 192.168.10.5 or {{ip}}", "attr": "ipaddress"},
            {"value": "set_ipv6address", "name": "IPv6 Address",
             "desc": "Set the host's IPv6 address.",
             "param": "e.g. 2001:db8::5 or {{ipv6}}", "attr": "ipv6address"},
            {"value": "set_agent", "name": "Checkmk Agent",
             "desc": "Set how the host is monitored — Checkmk agent, API "
                     "integrations, both, or none.",
             "param": "Pick a value", "attr": "tag_agent",
             "values": ["cmk-agent", "all-agents", "special-agents", "no-agent"]},
            {"value": "set_snmp", "name": "SNMP",
             "desc": "Set the host's SNMP monitoring.",
             "param": "Pick a value", "attr": "tag_snmp_ds",
             "values": ["no-snmp", "snmp-v1", "snmp-v2"]},
            {"value": "set_piggyback", "name": "Piggyback",
             "desc": "Set the host's piggyback behaviour.",
             "param": "Pick a value", "attr": "tag_piggyback",
             "values": ["auto-piggyback", "piggyback", "no-piggyback"]},
            {"value": "set_criticality", "name": "Criticality",
             "desc": "Set the host's criticality (Checkmk default tag group; "
                     "values may differ if customized).",
             "param": "Pick or type a value", "attr": "tag_criticality",
             "values": ["prod", "critical", "test", "offline"]},
            {"value": "set_networking", "name": "Networking Segment",
             "desc": "Set the host's networking segment (Checkmk default tag "
                     "group; values may differ if customized).",
             "param": "Pick or type a value", "attr": "tag_networking",
             "values": ["lan", "wan", "dmz"]},
            {"value": "set_alias", "name": "Alias",
             "desc": "Set the host's alias.",
             "param": "e.g. {{description}}", "attr": "alias"},
            {"value": "set_site", "name": "Monitored on Site",
             "desc": "Set which Checkmk site monitors the host.",
             "param": "Checkmk site id, e.g. cmk", "attr": "site"},
        ],
    },
    {
        "group": "Cluster & Parents",
        "actions": [
            {"value": "create_cluster", "name": "Create Cluster",
             "desc": "Create a cluster. Specify nodes as wildcard (*) and/or "
                     "comma separated.",
             "param": "Node tags, e.g. node-*"},
            {"value": "set_parent", "name": "Set Parents",
             "desc": "Comma separated list of parents.",
             "param": "parent1,parent2"},
        ],
    },
    {
        "group": "Labels",
        "actions": [
            {"value": "prefix_labels", "name": "Prefix Labels",
             "desc": "Prefix all labels with the given string.",
             "param": "Prefix"},
            {"value": "only_update_prefixed_labels", "name": "Update only Prefixed Labels",
             "desc": "Only update labels that carry the given prefix.",
             "param": "Prefix"},
            {"value": "dont_update_prefixed_labels", "name": "Don't update Prefixed Labels",
             "desc": "Do not update labels that carry the given prefix.",
             "param": "Prefix"},
        ],
    },
    {
        "group": "Opt-outs",
        "actions": [
            {"value": "dont_move", "name": "Don't Move",
             "desc": "Don't move the host to another folder after initial creation.",
             "param": ""},
            {"value": "dont_update", "name": "Don't Update",
             "desc": "Don't update host attributes after initial creation.",
             "param": ""},
            {"value": "dont_create", "name": "Don't Create",
             "desc": "Don't create the host if missing, but still update it.",
             "param": ""},
        ],
    },
    {
        "group": "Deprecated",
        "actions": [
            {"value": "value_as_folder", "name": "Value as Folder",
             "desc": "Use Move to Folder with Jinja instead.",
             "param": "", "deprecated": True},
            {"value": "attribute", "name": "Attribute",
             "desc": "Migrate to a Custom Checkmk Attribute: key:{{yourattribute}}.",
             "param": "", "deprecated": True},
            {"value": "multiple_custom_attribute", "name": "Multiple Custom Attribute",
             "desc": "Just switch to a normal Custom Attribute.",
             "param": "", "deprecated": True},
        ],
    },
]

# Flat (value, label) choices for the model field and the outcome summary.
action_outcome_types = [
    (action["value"], action["name"])
    for group in ACTION_CATALOG for action in group["actions"]
]

# Built-in convenience actions -> the Checkmk host attribute they set. These
# just make common attributes (IP, address family, agent, SNMP) easy to pick
# without knowing the attribute key; at export they populate custom_attributes.
BUILTIN_ATTRIBUTE_ACTIONS = {
    action["value"]: action["attr"]
    for group in ACTION_CATALOG for action in group["actions"]
    if action.get("attr")
}

# Actions no longer selectable for new rules. Legacy rules may still carry
# them, but such rules can no longer be saved until the action is migrated.
DEPRECATED_ACTIONS = {
    action["value"]
    for group in ACTION_CATALOG for action in group["actions"]
    if action.get("deprecated")
}

class CheckmkRuleOutcome(db.EmbeddedDocument):
    """
    ## Checkmk Rule Outcome

    Pick an **action** and its **parameter**. Most parameters support Jinja,
    so you can reference host attributes like `{{hostname}}` or `{{os}}`.

    ### Folder Options (Attributes & WATO permissions)

    The `Move to Folder` and `Create Folder` actions accept **folder options**:
    append `|{...}` (a Python dict) to any folder segment to set that folder's
    Checkmk attributes. Every key is a normal Checkmk folder attribute.

    The button **Edit folder attributes** below the value opens an editor with
    one card per folder level, so you do not have to write the dict by hand.

    Examples (parameter of a `Move to Folder` action):

    ```
    linux|{'title': 'Linux Servers'}
    linux/prod|{'tag_criticality': 'prod', 'site': 'remote_1'}
    ```

    #### Contact groups / WATO permissions

    Contact groups are the folder attribute `contactgroups`. Its value is a
    dict; `groups` is the list of contact groups, `use` grants those groups
    permission on the folder:

    ```
    linux/{{customer}}|{'contactgroups': {'groups': ['team_{{customer}}'], 'use': True}}
    ```

    Optional flags inside `contactgroups`: `recurse_use` (also add the groups
    as contacts to hosts in all sub-folders) and `recurse_perms` (also grant
    permission on sub-folders).

    #### Merging across hosts

    When several hosts land in the **same folder** but define **different**
    contact groups, the syncer **unions** their `groups` (duplicates removed)
    so the folder ends up with the contact groups of all its hosts. Scalar
    options like `title` or `site` keep the first host's value. The syncer is
    the source of truth: the merged group list replaces whatever is set on the
    folder in Checkmk.
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

    ### Keep manual Value
    When enabled the Value is only written once, on rule creation. On later
    syncs the Syncer keeps the rule but no longer overwrites its Value, so an
    operator can adjust it in Checkmk. A hint is added to the rule's
    description and comment in Checkmk.

    ### Enforce exact Value
    By default keys which exist only in Checkmk are accepted as defaults of
    the ruleset, so removing a key from the Value Template is not applied.
    Enable this to compare both values exactly, which pushes removed keys
    too. Only enable it when needed: if Checkmk adds defaults to this
    ruleset on save, the rule is rewritten on every run.
    """

    ruleset = db.StringField()
    folder = db.StringField(required=True)
    folder_index = db.IntField(default=0)
    comment = db.StringField()
    keep_value = db.BooleanField(default=False)
    enforce_value = db.BooleanField(default=False)
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
    # Denormalised first-outcome ruleset so the admin list can sort and
    # group by it directly (and search hits it via a top-level field).
    # Maintained by `CheckmkMngmtRuleView.on_model_change`.
    primary_ruleset = db.StringField()
    render_cmk_rule_mngmt = db.StringField()
    last_match = db.BooleanField(default=False)
    # Host-independent rule: its outcome templates and conditions never
    # reference host data, so it resolves to the same Checkmk rule(s) for
    # every host. The export renders it exactly once against an empty
    # context (host match conditions are ignored) instead of recomputing
    # it per host and de-duplicating the identical copies.
    static_rule = db.BooleanField(default=False)
    # Name of the Project this rule belongs to (or empty for a
    # free/global rule). Referenced by name — not as a ReferenceField — so a
    # project and its rules survive a JSON im-/export between separate syncer
    # instances without ObjectId remapping. Project rules are excluded from
    # the global ``export_rules`` and only pushed through the project workflow.
    project = db.StringField()
    enabled = db.BooleanField()
    meta = {
        'strict': False,
        'indexes': ['primary_ruleset', 'project'],
    }

#.


#.
#   .-- Checkmk Notification Rules

class NotificationRuleOutcome(db.EmbeddedDocument):
    """
    ## Notification Rule Outcome

    Each outcome turns into one Checkmk notification rule per matching
    host (after de-duplication of identical rendered bodies). All
    template fields support Jinja and have access to the host's
    attributes. Empty fields disable the corresponding condition.
    """
    notification_method = db.StringField(default='mail')
    # Parameter list a third-party notification script is called with.
    # Checkmk requires it for a custom plug-in; a built-in plug-in takes
    # its parameters from its own, admin-owned parameter set instead and
    # ignores this field.
    notification_parameters = db.StringField()

    # Loop: build one rule per entry of a list instead of one per host.
    # The current entry is available to every field below as {{name}}.
    multiply_by_list = db.BooleanField(default=False)
    multiply_list = db.StringField()

    # Recipients
    contact_group_recipients = db.StringField()

    # Match: groups
    match_contact_groups = db.StringField()
    match_host_groups = db.StringField()
    match_service_groups = db.StringField()

    # Match: event types — choices are enforced by the form widget
    # (see CheckmkNotificationRuleView), kept off the field itself so
    # `models.py` stays free of presentation constants.
    match_host_event_types = db.ListField(field=db.StringField())
    match_service_event_types = db.ListField(field=db.StringField())

    # Match: scope
    match_sites = db.StringField()
    match_folder = db.StringField()
    match_hosts = db.StringField()
    match_exclude_hosts = db.StringField()
    match_services = db.StringField()
    match_exclude_services = db.StringField()
    match_host_labels = db.StringField()
    match_service_labels = db.StringField()
    match_host_tags = db.StringField()
    match_check_types = db.StringField()
    match_plugin_output = db.StringField()
    match_only_during_time_period = db.StringField()
    match_service_levels = db.StringField()
    match_contacts = db.StringField()

    disable_rule = db.BooleanField(default=False)

    meta = {
        'strict': False,
    }


class CheckmkNotificationRule(db.Document):
    """
    Generate Checkmk notification rules from host attributes.
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField() # Helper for Preview

    outcomes = db.ListField(
        field=db.EmbeddedDocumentField(document_type="NotificationRuleOutcome"))
    render_cmk_notification_rule = db.StringField()

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
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
    user_id = db.StringField(required=True)
    full_name = db.StringField(required=True)
    email = db.StringField()
    pager_address = db.StringField()

    roles = db.ListField(field=db.StringField(), default=['admin'])
    contact_groups = db.ListField(field=db.StringField(), default=['all'])

    password = db.StringField(required=True)
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
    name = db.StringField(unique=True, sparse=True)
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
#   .-- Site Pools
class CheckmkSitePoolMember(db.EmbeddedDocument):
    """
    One Checkmk site inside a Site Pool
    """
    site_id = db.StringField(required=True) # Checkmk site id, e.g. berlin_1
    hosts_taken = db.IntField(default=0) # Managed by the engine, read-only in the form

    meta = {
        'strict': False,
    }

class CheckmkSitePool(db.Document):
    """
    Site Pool

    A named group of Checkmk sites hosts are spread across for load balancing.
    Used via the ``site_pool`` rule action. Assignment is least-loaded (the
    site with the fewest hosts wins) and sticky (a host keeps its site until
    the rule stops matching).
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    member_sites = db.ListField(
        field=db.EmbeddedDocumentField(document_type="CheckmkSitePoolMember"))
    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }
#.
#   .-- Rewrite Attributes
analysis_states = [
    ('running', "Running"),
    ('done', "Done"),
    ('failed', "Failed"),
]


class CheckmkRuleAnalysis(db.Document):
    """
    State and result of the last 'analyse_rules' run.

    The analysis walks every host twice, far too long for a web request,
    so the web interface starts it in the background and reads the result
    from here.

    One document per account (empty name = a run without one), replaced
    on every run. A snapshot, not a history — it cannot grow.
    """
    account = db.StringField(default='', unique=True)
    state = db.StringField(choices=analysis_states, default='running')
    error = db.StringField()
    started_at = db.DateTimeField()
    finished_at = db.DateTimeField()
    min_hosts = db.IntField(default=10)
    findings = db.ListField(field=db.DictField())

    meta = {
        'strict': False,
    }


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
    installation_staging_path = db.StringField()
    inital_password = db.StringField()

    subscription_username = db.StringField()
    subscription_password = db.StringField()

    # CheckMK API Credentials for automation
    cmk_user = db.StringField()
    cmk_secret = db.StringField()
    cmk_server_address = db.StringField()

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
    last_export_hash = db.StringField()

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

    # Host-independent DCD rule: a DCD connection rarely depends on host data, so
    # a static rule is rendered once (against an empty host context, ignoring the
    # match conditions) instead of once per host and de-duplicated — the same
    # optimisation CheckmkRuleMngmt.static_rule provides for Setup rules.
    static_rule = db.BooleanField(default=False)

    # Name of the Project this DCD rule belongs to (or empty).
    # Referenced by name to match CheckmkRuleMngmt.project. A DCD rule assigned
    # to a project follows that project's account filter (limit_by_accounts) on
    # export, just like a Setup rule — it is only exported to the accounts the
    # project allows. A rule without a project stays global.
    project = db.StringField()

    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
        'indexes': ['project'],
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
