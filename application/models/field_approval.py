"""
Field-level approval queue.

A pending change to a 'critical' label, captured at edit time and held
back from the host until a second user reviews it. Critical labels are
listed in `app.config['APPROVAL_REQUIRED_LABELS']`; any change to one
of those labels by anyone without the `approval_bypass` role enters the
queue instead of going straight to the Host document.
"""
import datetime
from application import db
from application.helpers.retention import register_retention, retention_seconds

# How long a decided approval stays readable. Pending entries are never
# touched — they have no decision date for the TTL to work from.
RETENTION_KEY = 'FIELD_APPROVAL_RETENTION_DAYS'
DEFAULT_RETENTION_DAYS = 365


_STATUS_CHOICES = (
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
)


class FieldApproval(db.Document):
    """
    A queued change to a single label on a single host.

    `host_id` is stored as a string so the document survives even if the
    host is later renamed or hard-deleted (rare but possible). The
    queue is read by humans, not by import logic.
    """
    host_id = db.StringField(required=True, max_length=64)
    hostname = db.StringField(max_length=255)
    field_name = db.StringField(required=True, max_length=255)
    old_value = db.StringField()
    new_value = db.StringField()

    requested_by_email = db.StringField(required=True, max_length=255)
    requested_at = db.DateTimeField(default=datetime.datetime.utcnow,
                                    required=True)

    status = db.StringField(choices=_STATUS_CHOICES, default='pending')
    decided_by_email = db.StringField(max_length=255)
    decided_at = db.DateTimeField()
    decision_reason = db.StringField(max_length=500)

    meta = {
        'collection': 'field_approval',
        'indexes': [
            {'fields': ['status', '-requested_at']},
            {'fields': ['host_id']},
            # Decided entries expire; pending ones carry no `decided_at`
            # and a TTL index ignores documents whose field is missing,
            # so nothing waiting for a decision is ever dropped.
            {'fields': ['decided_at'],
             'expireAfterSeconds': retention_seconds(
                 RETENTION_KEY, DEFAULT_RETENTION_DAYS)},
        ],
        'ordering': ['-requested_at'],
    }

    def __str__(self):
        return (f"FieldApproval[{self.status}] {self.hostname}."
                f"{self.field_name}: {self.old_value!r} -> {self.new_value!r}")


register_retention('Decided field approvals', FieldApproval, 'decided_at',
                   RETENTION_KEY, DEFAULT_RETENTION_DAYS)
