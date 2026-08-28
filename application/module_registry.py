"""
Descriptions and icons for the entries of the "Modules" menu.

Everything the module Overview pages show comes from here: the short
introduction at the top of a module's page, the one-liner printed on each
tile, and the icon the module carries in the menu.

An icon is a ``(type, value)`` pair as Flask-Admin expects it: a file
below ``static/vendor/`` — see the README there for why those are neutral
marks and not the vendors' logos — the syncer's own mark, or a Font
Awesome class. Every icon is served from ``static/``; the syncer runs in
offline installations, so nothing here may point at an external URL.

Entries are keyed by the menu name used in the plugin's
``register_admin_views``. Names that several modules share (Filter,
Rewrite Attributes, …) fall back to ``GENERIC_ENTRIES``, so a plugin only
needs its own key when it does something out of the ordinary.
"""

DOCS = 'https://docs.cmdbsyncer.de/'


def _docs(page):
    """Absolute link into the public documentation."""
    return f'{DOCS}{page}/'


#   .-- Modules
MODULES = {
    'Modules': {
        'icon': ('fa', 'fa-puzzle-piece'),
        'intro': (
            "Modules are the systems the syncer writes to and reads from. "
            "Each module brings its own rules: what is exported, how "
            "attributes are translated, and which objects the target system "
            "gets. Pick a module to see everything it offers."
        ),
        'docs': _docs('basics/how_it_works'),
    },
    'Checkmk': {
        'icon': ('image', 'vendor/checkmk.svg'),
        'intro': (
            "Export hosts to Checkmk and keep its configuration in sync: "
            "folders and host attributes, host tags, groups, users, "
            "downtimes, notification and Setup rules. Checkmk data can also "
            "be inventorized back into the syncer, so labels and monitoring "
            "state become usable in rules."
        ),
        'docs': _docs('checkmk'),
    },
    'Netbox': {
        'icon': ('image', 'vendor/netbox.svg'),
        'intro': (
            "Keep Netbox filled from the syncer's objects. Every Netbox "
            "area has its own attribute rules — devices and interfaces "
            "under DCIM, addresses and prefixes under IPAM, clusters and "
            "virtual machines under Virtualization, plus contacts."
        ),
        'docs': _docs('netbox'),
    },
    'Ansible': {
        'icon': ('image', 'vendor/ansible.svg'),
        'intro': (
            "Serve Ansible with a dynamic inventory built from the syncer's "
            "objects, hand over host variables, and run playbooks straight "
            "from the web interface — manually or triggered by rules."
        ),
        'docs': _docs('ansible'),
    },
    'i-doit': {
        'icon': ('image', 'vendor/idoit.svg'),
        'intro': (
            "Exchange objects with i-doit: import the CMDB's objects into "
            "the syncer and write attributes back into i-doit's categories."
        ),
        'docs': _docs('i-doit'),
    },
    'Jira Cloud': {
        'icon': ('image', 'vendor/jira.svg'),
        'intro': (
            "Export objects into Jira Cloud — as issues or as entries of a "
            "Jira asset schema — and control per rule which fields are "
            "filled from which syncer attributes."
        ),
        'docs': _docs('jira'),
    },
    'LDAP': {
        # No vendor here — LDAP is a protocol, so the directory mark stands
        # for every server that speaks it
        'icon': ('fa', 'fa-address-book'),
        'intro': (
            "Read objects out of an LDAP directory — Active Directory or "
            "any other server: import them as objects of the syncer, "
            "inventorize their attributes, and search the directory to see "
            "under which name an object really is stored."
        ),
        'docs': _docs('ldap'),
    },
    'VMware': {
        'icon': ('image', 'vendor/vmware.svg'),
        'intro': (
            "Import virtual machines and their vCenter data into the syncer "
            "and hand custom attributes back to VMware."
        ),
        'docs': _docs('vmware'),
    },
    'Syncer Rules': {
        # The syncer's own mark — these rules are the syncer's, not a vendor's.
        'icon': ('image', 'cmdbsyncer_mark.png'),
        'intro': (
            "Let the syncer write its own rules: an automation rule "
            "generates the rule records other modules use, so recurring "
            "rule sets don't have to be maintained by hand."
        ),
        'docs': _docs('basics/auto_rules'),
    },
}
#.

#   .-- Sub categories
SUB_CATEGORIES = {
    'Manage Business Intelligence': (
        "Build Checkmk BI aggregations and the rules they are made of."
    ),
    'Pools': (
        "Distribute hosts over a set of folders or sites instead of "
        "pinning every host individually."
    ),
    'Checkmk Server': (
        "Administration of the Checkmk server itself — its sites and their "
        "creation, update and configuration."
    ),
    'Rules': (
        "All rule types that decide what Ansible receives and when a "
        "playbook runs."
    ),
    'Plugin: Dataflow': (
        "Support for the Netbox Dataflow plugin — its models and the fields "
        "the syncer fills."
    ),
}
#.

#   .-- Generic entries
GENERIC_ENTRIES = {
    'Filter': (
        "Decide which objects this module handles at all, and which of "
        "their attributes are allowed to leave the syncer."
    ),
    'Rewrite Attributes': (
        "Rename attribute keys and rewrite their values before the export, "
        "or build new attributes out of existing ones."
    ),
    'Custom Attributes': (
        "Define which attributes this module writes to the target system "
        "and where their values come from."
    ),
}
#.

#   .-- Entries
ENTRIES = {
    'Modules': {
        'Global Custom Attributes': (
            "Attributes computed once for every object and available to "
            "all modules — the place for values more than one target needs."
        ),
    },
    'Checkmk': {
        'Rewrite and Create Custom Syncer Attributes': (
            "Rename attribute keys and rewrite their values, or compose new "
            "syncer attributes out of the ones an import delivered."
        ),
        'Filter Hosts and Whiteliste Checkmk Labels': (
            "Decide which hosts are exported to Checkmk at all and which of "
            "their attributes are allowed to become Checkmk labels."
        ),
        'Limit Host Export to Folders': (
            "Restrict a single account's host export to selected folders — "
            "useful to roll out a new configuration on a small scope first."
        ),
        'Set Folder and  Attributes of Host': (
            "The central export rule: which folder a host lands in and "
            "which Checkmk host attributes it is given."
        ),
        'Manage Host-/Contact-/Service- Groups': (
            "Create host, contact and service groups in Checkmk and keep "
            "their members in sync with the syncer's attributes."
        ),
        'Manage Checkmk Setup Rules': (
            "Generate Checkmk Setup rules (rulesets) from syncer data and "
            "keep them up to date, including their conditions."
        ),
        'Manage Hosttags': (
            "Maintain Checkmk's host tag groups and their tags so the tags "
            "exported hosts refer to actually exist."
        ),
        'Manage Checkmk Users': (
            "Create and update Checkmk users together with their roles and "
            "contact groups."
        ),
        'Manage Downtimes': (
            "Set and remove downtimes in Checkmk by rule — for example for "
            "hosts in a maintenance state."
        ),
        'Manage Notification Rules': (
            "Maintain Checkmk's notification rules from the syncer instead "
            "of clicking them together per site."
        ),
        'Manage DCD Rules': (
            "Maintain the connections of Checkmk's Dynamic Configuration "
            "Daemon that pick up the exported hosts."
        ),
        'Manage Password Store': (
            "Fill Checkmk's password store, so rules can reference secrets "
            "without the passwords ending up in the configuration."
        ),
        'Inventorize from Checkmk Settings': (
            "Choose which data the syncer reads back from Checkmk — labels, "
            "HW/SW inventory or service state — to use it in rules."
        ),
        'Cache': (
            "Read-only view of the Checkmk objects the syncer has cached, "
            "handy when checking what the last run actually saw."
        ),
        'Data Quality Check': (
            "Check a list of host names against a Checkmk site: is the host "
            "known, does its agent answer, who may see it."
        ),
        'BI Aggregation': (
            "Define the Checkmk BI aggregations the syncer creates."
        ),
        'BI Rule': (
            "Define the BI rules the aggregations are built from."
        ),
        'Folder Pools': (
            "Spread hosts over a fixed set of folders, each with its own "
            "capacity."
        ),
        'Site Pools': (
            "Spread hosts over several Checkmk sites, each with its own "
            "capacity."
        ),
        'Checkmk Site Updates and Creation': (
            "Create sites on a Checkmk server, update them and manage their "
            "version."
        ),
        'Site Settings': (
            "Per-site configuration the syncer rolls out to the Checkmk "
            "server."
        ),
    },
    'Netbox': {
        'DCIM: Devices': (
            "Which fields of a Netbox device the syncer fills, and from "
            "which attributes."
        ),
        'DCIM: Interfaces': (
            "Attributes of the interfaces the syncer creates on Netbox "
            "devices."
        ),
        'IPAM: IP Addresses': (
            "Attributes of the IP addresses written to Netbox's IPAM."
        ),
        'IPAM: Prefix': (
            "Attributes of the prefixes written to Netbox's IPAM."
        ),
        'Virtualization: Cluster': (
            "Attributes of the virtualization clusters kept in Netbox."
        ),
        'Virtualization: Virtual Machines': (
            "Attributes of the virtual machines kept in Netbox."
        ),
        'Virtualization: Interfaces': (
            "Attributes of the interfaces on Netbox virtual machines."
        ),
        'Tenancy: Contacts': (
            "Contacts the syncer maintains under Netbox's tenancy and "
            "assigns to objects."
        ),
        'Model Defintion': (
            "Which Dataflow model the syncer writes and which field "
            "definitions belong to it."
        ),
        'Field Definition': (
            "The single fields a Dataflow model is made of."
        ),
    },
    'Ansible': {
        'Projects': (
            "The hub of the module: a project bundles the playbooks, the "
            "inventory and the rules that belong together."
        ),
        'Run Playbook': (
            "Start a playbook out of the web interface against the objects "
            "the project's inventory delivers."
        ),
        'Run History': (
            "Result and output of every playbook run the syncer started."
        ),
        'Ansible Attributes': (
            "The host variables Ansible receives with the dynamic "
            "inventory."
        ),
        'Playbook Fire Rules': (
            "Conditions under which a playbook starts on its own — for "
            "example when an object appears or changes."
        ),
    },
    'LDAP': {
        'Search Directory': (
            "Search an LDAP account's directory read only — find an object "
            "by a hostname with or without domain, by any attribute, or "
            "with an own filter before it goes into the account."
        ),
    },
    'Jira Cloud': {
        'Export Rules': (
            "Which Jira issues or asset entries an object becomes, and how "
            "their fields are filled."
        ),
        'Schema Cache': (
            "The Jira field and asset schema the syncer has read, so the "
            "rule forms can offer the real field names."
        ),
    },
    'Syncer Rules': {
        'Automate Syncer Rule Creation': (
            "Describe a rule once and let the syncer create and update the "
            "matching rule records of the other modules from it."
        ),
    },
}
#.


def get_module_info(module):
    """Icon / intro / docs link of a module — empty defaults when unknown."""
    return MODULES.get(module, {})


def get_module_icon(module):
    """The module's icon as ``(type, value)``, or ``(None, None)``."""
    return MODULES.get(module, {}).get('icon') or (None, None)


def get_entry_description(module, name, sub_menu=None):
    """
    Description of one menu entry: a text keyed by the sub menu it sits in
    first, then the module's own text, then the one shared by all modules.
    """
    for key in (sub_menu, module):
        text = ENTRIES.get(key, {}).get(name) if key else None
        if text:
            return text
    return GENERIC_ENTRIES.get(name, '')


def get_category_description(name):
    """Description of a sub category shown as a section headline."""
    return SUB_CATEGORIES.get(name, '')
