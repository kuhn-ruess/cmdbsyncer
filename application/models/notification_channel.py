"""
Shared NotificationChannel model.

Lives in OSS so both the Enterprise notifications feature and future
OSS notification pipelines point at the same collection. OSS ships
the Email type only; Enterprise calls `register_channel_type()` on
feature activation to extend the dropdown with Slack / Teams / generic
webhook. Collection name is `notification_channel` (MongoEngine default
for the class name) — matches existing Enterprise installs, so no
migration is needed.
"""
from application import db


# Mutable on purpose — Enterprise appends slack / msteams / webhook at
# feature-activation time. MongoEngine validation and Flask-Admin both
# read this on demand, so late additions show up in the dropdown.
CHANNEL_TYPE_CHOICES = [
    ('email', 'Email (SMTP via the syncer Mail config)'),
]


def register_channel_type(value, label):
    """Add a channel type. Idempotent.

    Called by Enterprise when the notifications feature is active to
    plug in slack / msteams / webhook.
    """
    if not any(v == value for v, _ in CHANNEL_TYPE_CHOICES):
        CHANNEL_TYPE_CHOICES.append((value, label))


class NotificationChannel(db.Document):
    """A delivery target (email address, Slack webhook, …).

    OSS only knows how to deliver the `email` type natively (via the
    Flask-Mail config). The Enterprise notifications module provides
    dispatchers for the other types; when Enterprise is missing, a
    non-email channel falls back to email-to-contact so OSS installs
    still get something delivered.

    All type-specific fields are stored on the same document so one
    record can be retargeted from slack → email without losing
    configuration.
    """
    name = db.StringField(required=True, unique=True, max_length=255)
    type = db.StringField(choices=CHANNEL_TYPE_CHOICES, required=True,
                          default='email')
    enabled = db.BooleanField(default=True)
    description = db.StringField()

    # Email — empty `email_recipients` = deliver to the contact's own
    # address. Prefix prepends to the event title.
    email_recipients = db.StringField()
    email_subject_prefix = db.StringField()

    # Slack / Teams / generic webhook (Enterprise-driven)
    webhook_url = db.StringField()
    # Kept for backwards compatibility with existing Enterprise installs
    # whose generic-webhook HMAC secret was an env-var name. New setups
    # should use `signing_secret_account` (password comes from Account).
    webhook_secret_env = db.StringField()
    signing_secret_account = db.StringField()
    slack_channel = db.StringField()
    slack_mention = db.StringField()
    extra_headers = db.DictField()

    meta = {'collection': 'notification_channel', 'strict': False,
            'indexes': [{'fields': ['name'], 'unique': True}]}

    def __str__(self):
        return f'{self.name} ({self.type})'
