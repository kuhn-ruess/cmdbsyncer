"""
Label history behind the host "Timeline" tab.

One document per *event*, not per label: a host save that changes ten
labels writes one document carrying ten entries. The first design wrote
one document per changed label, which turned a fleet whose import
rewrites labels on every run into hundreds of millions of rows — with
indexes larger than the data itself.

Bounded on two sides: nothing is written unless LABEL_HISTORY_ENABLED
is set, and a TTL index drops events older than
LABEL_HISTORY_RETENTION_DAYS. `sys self_configure` keeps that TTL in
sync with the configured value; `sys purge_label_history` cleans up
what earlier versions left behind.
"""
# pylint: disable=too-few-public-methods
import datetime

from mongoengine import CASCADE

from application import db
from application.helpers.label_history import (
    DEFAULT_RETENTION_DAYS, RETENTION_KEY, label_history_retention_seconds,
)
from application.helpers.retention import register_retention


class HostLabelChange(db.EmbeddedDocument):
    """
    One label that moved inside a `HostLabelEvent`: added, updated or
    removed, with the values before and after.
    """
    key = db.StringField(required=True, max_length=255)
    old_value = db.StringField()
    new_value = db.StringField()
    change = db.StringField(
        choices=[
            ('add', 'added'), ('update', 'updated'), ('remove', 'removed'),
        ],
        required=True,
    )


class HostLabelEvent(db.Document):
    """One recorded label change of one host, with every label it moved."""
    host = db.ReferenceField(document_type='Host',
                             required=True, reverse_delete_rule=CASCADE)
    changed_at = db.DateTimeField(default=datetime.datetime.utcnow, required=True)
    source = db.StringField(default='import')  # import | manual | template | rule
    user_email = db.StringField()
    changes = db.ListField(
        field=db.EmbeddedDocumentField(document_type='HostLabelChange')
    )

    meta = {
        'collection': 'host_label_event',
        'indexes': [
            {'fields': ['host', '-changed_at']},
            {'fields': ['changed_at'],
             'expireAfterSeconds': label_history_retention_seconds()},
        ],
        'ordering': ['-changed_at'],
    }


register_retention('Label history', HostLabelEvent, 'changed_at',
                   RETENTION_KEY, DEFAULT_RETENTION_DAYS)
