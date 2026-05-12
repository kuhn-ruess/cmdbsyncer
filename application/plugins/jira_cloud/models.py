"""
Jira Cloud Export Models
"""
# pylint: disable=too-few-public-methods
from application import db
from application.modules.rule.models import rule_types


class JiraExportOutcome(db.EmbeddedDocument):
    """
    One field mapping: a Jira attribute on a specific object type
    receives a (Jinja-rendered) value.

    Object type and attribute are stored together in a single ``target``
    string of the form ``"<object_type_id>|<attribute_name>"``.  In
    Jira Assets, attributes belong to their type — attribute "Name" on
    "Hardware Server" is a different attribute from "Name" on
    "Laptop", with different ids — so the GUI presents a single
    dropdown over all (type, attribute) pairs and that's what we store.
    """
    target = db.StringField(required=True)
    value = db.StringField()
    meta = {
        'strict': False,
    }

    @property
    def object_type_id(self):
        """Convenience accessor: int part of ``target``."""
        if not self.target or '|' not in self.target:
            return None
        try:
            return int(self.target.split('|', 1)[0])
        except (ValueError, TypeError):
            return None

    @property
    def jira_attribute(self):
        """Convenience accessor: name part of ``target``."""
        if not self.target or '|' not in self.target:
            return ''
        return self.target.split('|', 1)[1]


class JiraExportRule(db.Document):
    """
    Defines which hosts get exported to Jira Cloud Assets and which
    fields are written.

    The set of target object types follows from the rule's outcomes
    (one outcome = one field on one object type) — a single rule may
    cover several object types at once.
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField()  # GUI preview helper

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type='JiraExportOutcome'))
    render_jira_export_outcome = db.StringField()  # GUI preview helper

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField(default=True)
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False,
    }


class JiraCloudRewriteAttributeRule(db.Document):
    """
    Rewrite host attribute keys/values before the export rule engine
    evaluates them — mirrors the Checkmk / Netbox rewrite pattern.
    """
    name = db.StringField()
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type='FullCondition'))
    render_full_conditions = db.StringField()  # GUI preview helper

    outcomes = db.ListField(
        field=db.EmbeddedDocumentField(document_type='AttributeRewriteAction'))
    render_attribute_rewrite = db.StringField()  # GUI preview helper

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField(default=True)
    sort_field = db.IntField(default=0)
    meta = {
        'strict': False,
    }


class JiraCloudFilterRule(db.Document):
    """
    Exclude hosts from the Jira Cloud export.

    Mirrors the Checkmk pattern: hosts matching this rule (any
    ``ignore_hosts`` filter action) are dropped by the Plugin base
    class's ``get_attributes`` before the export rule engine sees them.
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField()  # GUI preview helper

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="FilterAction"))
    render_filter_outcome = db.StringField()  # GUI preview helper

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField(default=True)
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
    }


class JiraSchemaAttribute(db.EmbeddedDocument):
    """One attribute belonging to an object type."""
    attribute_id = db.IntField(required=True)
    name = db.StringField(required=True)
    type_name = db.StringField()
    editable = db.BooleanField(default=True)
    meta = {
        'strict': False,
    }


class JiraSchemaObjectType(db.EmbeddedDocument):
    """One Jira Assets object type with its attributes."""
    object_type_id = db.IntField(required=True)
    name = db.StringField(required=True)
    schema_id = db.IntField()
    schema_name = db.StringField()
    attributes = db.ListField(field=db.EmbeddedDocumentField(document_type='JiraSchemaAttribute'))
    meta = {
        'strict': False,
    }


class JiraSchemaCache(db.Document):
    """
    Per-account snapshot of the Jira Cloud Assets schema.

    Populated by `cmdbsyncer jira sync_schema <account>` and consumed by
    the export plugin (attribute-name → id resolution, validation) and
    by the GUI (autocomplete suggestions in the rule form).
    """
    account = db.StringField(required=True, unique=True)
    updated = db.DateTimeField()
    object_types = db.ListField(
        field=db.EmbeddedDocumentField(document_type='JiraSchemaObjectType'))
    meta = {
        'strict': False,
    }
