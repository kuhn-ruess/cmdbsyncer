"""
Event Driven Ansible: rules and the history of the events sent
"""
# pylint: disable=too-few-public-methods
from application import db
from application.helpers.retention import register_retention, retention_seconds
from application.modules.rule.models import rule_types

# A host that keeps matching gets its event again after this many hours,
# so a registration that failed on the Ansible side is retried.
DEFAULT_RESEND_HOURS = 24

# Retention of the event history.
EVENT_LOG_RETENTION_KEY = 'EDA_EVENT_LOG_RETENTION_DAYS'
DEFAULT_EVENT_LOG_RETENTION_DAYS = 90

event_statuses = [
    ('success', 'Success'),
    ('failure', 'Failure'),
]


class EdaEventAction(db.EmbeddedDocument):
    """
    One event a matching host sends to Event Driven Ansible.

    `event` is the name the rulebook matches on. `extra_vars` is YAML
    (Jinja rendered with the host attributes first) and travels as the
    `vars` of the event.
    """
    event = db.StringField(required=True)
    extra_vars = db.StringField()
    resend_after_hours = db.IntField(default=DEFAULT_RESEND_HOURS)

    meta = {
        'strict': False,
    }


class EdaEventRule(db.Document):
    """
    Rule deciding which hosts send which events to Event Driven Ansible.
    Evaluated by the `eda send_events` command (and its cronjob), never
    on an inventory or export run.
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    condition_typ = db.StringField(choices=rule_types)
    conditions = db.ListField(field=db.EmbeddedDocumentField(document_type="FullCondition"))
    render_full_conditions = db.StringField()  # Helper for preview

    outcomes = db.ListField(field=db.EmbeddedDocumentField(document_type="EdaEventAction"))
    render_eda_outcomes = db.StringField()  # Helper for preview

    last_match = db.BooleanField(default=False)
    enabled = db.BooleanField()
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
    }


class EdaEventLog(db.Document):
    """
    One event sent (or tried) to Event Driven Ansible. Read-only audit
    record, and the base for not sending the same event again before
    `resend_after_hours` have passed.
    """
    account = db.StringField()
    rule_id = db.StringField()
    rule_name = db.StringField()
    hostname = db.StringField()
    event = db.StringField()
    payload = db.StringField()

    sent_at = db.DateTimeField()
    status = db.StringField(choices=event_statuses)
    http_status = db.IntField()
    response = db.StringField()

    meta = {
        'strict': False,
        'indexes': [
            '-sent_at',
            ('account', 'rule_id', 'hostname', 'event', 'status'),
            {'fields': ['sent_at'],
             'expireAfterSeconds': retention_seconds(
                 EVENT_LOG_RETENTION_KEY, DEFAULT_EVENT_LOG_RETENTION_DAYS)},
        ],
    }


register_retention('EDA event history', EdaEventLog, 'sent_at',
                   EVENT_LOG_RETENTION_KEY, DEFAULT_EVENT_LOG_RETENTION_DAYS)
