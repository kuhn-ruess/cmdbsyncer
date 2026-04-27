"""
Shared NotificationRule model.

A rule routes one of two event sources to one or more channels:

    log    — every record written through `log.log(...)` (i.e. into the
             OSS Log view).
    audit  — every persisted AuditEntry.

Optional `match_pattern` is a regex that further narrows the events:
matched against the log message for `log` rules and against the audit
`event_type` for `audit` rules. `only_errors` (log rules only) limits
the rule to log entries flagged as errors.
"""
from application import db
from application.models.notification_channel import NotificationChannel


SOURCE_TYPES = [
    ('log', 'Log entries (log.log)'),
    ('audit', 'Audit log entries'),
]


class NotificationRule(db.Document):
    """One match-and-route rule. All matching enabled rules fire."""
    name = db.StringField(required=True, unique=True)
    enabled = db.BooleanField(default=True)
    priority = db.IntField(default=100)

    source_type = db.StringField(choices=SOURCE_TYPES, required=True,
                                 default='log')
    only_errors = db.BooleanField(default=False)
    match_pattern = db.StringField()

    channels = db.ListField(field=db.ReferenceField(document_type=NotificationChannel))

    title_template = db.StringField()
    message_template = db.StringField()

    cooldown_minutes = db.IntField(default=5)

    meta = {
        'collection': 'notification_rule',
        'strict': False,
        'indexes': [{'fields': ['source_type', 'enabled', 'priority']}],
    }

    def __str__(self):
        return self.name
