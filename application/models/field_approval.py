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
        ],
        'ordering': ['-requested_at'],
    }

    def __str__(self):
        return (f"FieldApproval[{self.status}] {self.hostname}."
                f"{self.field_name}: {self.old_value!r} -> {self.new_value!r}")
