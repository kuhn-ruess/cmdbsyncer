"""
Side-document for the full raw inventory tree of a host.

Each source plugin (Checkmk HW/SW inventory, future Netbox / VMware /
…) writes one ``HostInventoryTree`` per (hostname, source). The curated
subset configured in the source's inventory settings still lands on
``Host.inventory`` for the rule engine; this collection keeps the
un-curated payload off the host list view.
"""
# pylint: disable=too-few-public-methods
import datetime

from application import db


class HostInventoryTreePath(db.EmbeddedDocument):
    """One ``path: value`` node. Dotted paths preserved as a string so
    Mongo (which rejects dots in field names) accepts them."""
    path = db.StringField(required=True)
    value = db.DynamicField()


class HostInventoryTree(db.Document):
    """Full raw inventory tree per (hostname, source). ``previous_paths``
    carries one prior snapshot so the CMDB Tree tab can render an
    added/removed/changed diff against the last import."""
    hostname = db.StringField(required=True, max_length=255)
    source = db.StringField(required=True, max_length=120)
    paths = db.ListField(
        field=db.EmbeddedDocumentField(document_type='HostInventoryTreePath')
    )
    last_update = db.DateTimeField(default=datetime.datetime.utcnow)
    previous_paths = db.ListField(
        field=db.EmbeddedDocumentField(document_type='HostInventoryTreePath')
    )
    previous_update = db.DateTimeField()
    meta = {
        'collection': 'host_inventory_tree',
        'strict': False,
        'indexes': [
            {'fields': ('hostname', 'source'), 'unique': True},
            {'fields': ['hostname']},
        ],
    }
