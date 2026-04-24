"""
Shared NotificationRule model.

Routing rules for `notify_event(event_type, **context)` calls — cron
failures, recoveries, license expiry, secret-resolution failures,
audit events, …

Lives in OSS so the rule table + admin UI are always available even
without the Enterprise license; Enterprise ships the actual dispatcher
(Jinja templates, cooldown, rate-limiting) that consumes these rules.
Without Enterprise the rules are stored config — nothing fires — the
same tradeoff as non-email channel types.
"""
from application import db
from application.models.notification_channel import NotificationChannel


SEVERITIES = [
    ('info', 'info'),
    ('warning', 'warning'),
    ('error', 'error'),
    ('critical', 'critical'),
]


class NotificationRule(db.Document):
    """
    Match-and-route rule. First enabled rule whose matchers accept an
    event fires it (unless `continue_after_match`, in which case later
    rules can also fire). Rules are evaluated by ascending `priority`.
    """
    name = db.StringField(required=True, unique=True)
    enabled = db.BooleanField(default=True)
    priority = db.IntField(default=100)
    continue_after_match = db.BooleanField(default=False)

    # Matchers — all must be satisfied. Empty string means "any".
    event_type_match = db.StringField()    # regex on event_type
    severity_min = db.StringField(choices=SEVERITIES, default='info')
    source_match = db.StringField()        # regex on source
    target_match = db.StringField()        # regex on target_name
    outcome_match = db.StringField()       # "success" | "failure" | ""

    # Targets
    channels = db.ListField(field=db.ReferenceField(document_type=NotificationChannel))

    # Rendering (Jinja, consumed by the Enterprise dispatcher)
    title_template = db.StringField()
    message_template = db.StringField()

    # Rate-limiting (Enterprise dispatcher)
    cooldown_minutes = db.IntField(default=5)
    max_per_hour = db.IntField(default=20)

    meta = {
        'collection': 'notification_rule',
        'strict': False,
        'indexes': [{'fields': ['priority', 'enabled']}],
    }

    def __str__(self):
        return self.name
