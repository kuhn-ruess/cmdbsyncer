"""
Shared NotificationChannel model.

A channel is a thin record that points at a Syncer Account — the
Account carries the delivery endpoint (URL in ``address``), any
signing secret or bearer token (``password``) and per-integration
details like a default Slack channel or extra HTTP headers
(``custom_fields``). The dispatch code reads those through
``get_account_by_name`` so an Enterprise Secrets Manager binding is
applied transparently.

OSS delivers email natively via the Flask-Mail config when no Account
is set; Enterprise ships Account plugin types for Slack, MS Teams and
generic webhook.
"""
from application import db


# Mutable on purpose — Enterprise appends slack / msteams / webhook at
# feature-activation time. MongoEngine validation and Flask-Admin both
# read this on demand, so late additions show up in the dropdown.
CHANNEL_TYPE_CHOICES = [
    ('email', 'Email (SMTP via the syncer Mail config)'),
]


def register_channel_type(value, label):
    """Add a channel type. Idempotent."""
    if not any(v == value for v, _ in CHANNEL_TYPE_CHOICES):
        CHANNEL_TYPE_CHOICES.append((value, label))


class NotificationChannel(db.Document):
    """A delivery target (email address, Slack webhook, …)."""
    name = db.StringField(required=True, unique=True, max_length=255)
    type = db.StringField(choices=CHANNEL_TYPE_CHOICES, required=True,
                          default='email')
    enabled = db.BooleanField(default=True)
    description = db.StringField()

    # Name of the Syncer Account this channel delivers through. For
    # the non-email types the Account's ``address`` is the webhook URL
    # and its ``password`` is the optional signing / bearer secret.
    # Slack-specific overrides (#channel, mention) and generic webhook
    # headers live on the Account's ``custom_fields``. Email leaves
    # this blank and uses the global Flask-Mail config.
    account = db.StringField()

    # Email — empty ``email_recipients`` = deliver to the contact's
    # own address. Prefix prepends to the event title.
    email_recipients = db.StringField()
    email_subject_prefix = db.StringField()

    meta = {'collection': 'notification_channel', 'strict': False,
            'indexes': [{'fields': ['name'], 'unique': True}]}

    def __str__(self):
        return f'{self.name} ({self.type})'
