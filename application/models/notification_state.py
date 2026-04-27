"""
Per-rule cooldown bookkeeping for the notification dispatcher.

TTL-indexed so untouched keys self-expire after a day.
"""
from datetime import datetime
from application import db


class NotificationState(db.Document):
    """One row per dedup-key — last-sent timestamp + suppression counter."""
    dedup_key = db.StringField(required=True, unique=True)
    last_sent_at = db.DateTimeField()
    suppressed_count = db.IntField(default=0)

    meta = {
        'collection': 'notification_state',
        'strict': False,
        'indexes': [
            {'fields': ['dedup_key']},
            {'fields': ['last_sent_at'], 'expireAfterSeconds': 86400},
        ],
    }

    def touch(self):
        """Mark this dedup key as just-sent."""
        self.last_sent_at = datetime.utcnow()
