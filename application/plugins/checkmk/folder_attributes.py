"""
Catalog of the typical attributes of a Checkmk folder.

The ``Move to Folder`` / ``Create Empty Folder`` actions carry their folder
attributes as a Python dict behind a ``|`` (see ``CheckmkRuleOutcome``). The
rule form turns that syntax into per-folder input fields; this module is the
single place describing which attributes it offers and how each one is edited.
"""
from application.plugins.checkmk.models import ACTION_CATALOG

# Value lists of the built-in attribute actions, keyed by Checkmk attribute.
# The folder-attribute catalog below reuses them so a tag's values are
# maintained in exactly one place.
BUILTIN_ATTRIBUTE_VALUES = {
    action["attr"]: action["values"]
    for group in ACTION_CATALOG for action in group["actions"]
    if action.get("attr") and action.get("values")
}

# Typical attributes of a Checkmk *folder*, used by the folder builder on the
# rule form (see admin/model/_folder_builder.html) to turn the
# ``folder|{'key': value}`` syntax into per-folder input fields.
#   value  - the Checkmk folder attribute key
#   name   - label shown in the editor
#   desc   - one-line explanation
#   type   - how the editor renders and serializes the value:
#            text / choice (values) / bool / list (comma separated) /
#            kv (key-value pairs) / contactgroups (groups + permission flags)
FOLDER_ATTRIBUTE_CATALOG = [
    {"value": "title", "name": "Title", "type": "text",
     "desc": "Folder title shown in Checkmk instead of the folder name."},
    {"value": "contactgroups", "name": "Contact groups", "type": "contactgroups",
     "desc": "Contact groups of the folder, and who may edit it in Setup."},
    {"value": "site", "name": "Monitored on site", "type": "text",
     "desc": "Checkmk site id every host in this folder is monitored on."},
    {"value": "parents", "name": "Parents", "type": "list",
     "desc": "Comma separated list of parent hosts."},
    {"value": "labels", "name": "Labels", "type": "kv",
     "desc": "Folder labels, inherited by every host in the folder."},
    {"value": "tag_criticality", "name": "Criticality", "type": "choice",
     "values": BUILTIN_ATTRIBUTE_VALUES["tag_criticality"],
     "desc": "Checkmk default tag group; values may differ if customized."},
    {"value": "tag_networking", "name": "Networking segment", "type": "choice",
     "values": BUILTIN_ATTRIBUTE_VALUES["tag_networking"],
     "desc": "Checkmk default tag group; values may differ if customized."},
    {"value": "tag_agent", "name": "Checkmk agent", "type": "choice",
     "values": BUILTIN_ATTRIBUTE_VALUES["tag_agent"],
     "desc": "How the hosts in this folder are monitored."},
    {"value": "tag_snmp_ds", "name": "SNMP", "type": "choice",
     "values": BUILTIN_ATTRIBUTE_VALUES["tag_snmp_ds"],
     "desc": "SNMP monitoring of the hosts in this folder."},
    {"value": "tag_address_family", "name": "IP address family", "type": "choice",
     "values": BUILTIN_ATTRIBUTE_VALUES["tag_address_family"],
     "desc": "IP address family of the hosts in this folder."},
    {"value": "tag_piggyback", "name": "Piggyback", "type": "choice",
     "values": BUILTIN_ATTRIBUTE_VALUES["tag_piggyback"],
     "desc": "Piggyback behaviour of the hosts in this folder."},
    {"value": "snmp_community", "name": "SNMP credentials", "type": "text",
     "desc": "SNMP community of the hosts in this folder."},
]

# Sub-fields of the ``contactgroups`` attribute. ``groups`` is the list of
# contact groups; the flags control what the groups may do (WATO permissions).
CONTACTGROUP_FLAGS = [
    {"value": "use", "name": "Add these groups as contacts",
     "desc": "The groups become contacts of every host in this folder."},
    {"value": "use_for_services", "name": "Also for services",
     "desc": "The groups also become contacts of the hosts' services."},
    {"value": "recurse_use", "name": "Also for sub-folders",
     "desc": "Hosts in sub-folders get these contact groups too."},
    {"value": "recurse_perms", "name": "Permissions on sub-folders",
     "desc": "The groups may also edit the sub-folders in Setup."},
]
