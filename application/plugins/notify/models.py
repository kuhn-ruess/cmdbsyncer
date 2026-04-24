"""
Notification Hub — data model.

A local, self-hosted "who do we alert and how" layer. Sits between an
event source (Checkmk notification script is first, but the dispatch
endpoint is source-agnostic) and an actual delivery channel. The
delivery targets themselves (`NotificationChannel`) live in the shared
OSS model at `application.models.notification_channel`, so every
notification pipeline — the Hub and the Enterprise routing feature —
points at the same collection and the same admin UI.

Five kinds of data live here:

  NotifyContact           A person or endpoint (email, phone, channels).
  NotifyContactGroup      A named set of contacts, plus an optional
                          dynamic LDAP filter that re-resolves on every
                          dispatch.
  NotifyVacation          "Contact X is away from D1 to D2, route to Y
                          instead (or drop)."
  NotifyShiftCalendar     iCal / HTTPS calendar URL — the people whose
                          names appear in the currently-active event are
                          treated as on-call.
  NotifyDispatchRule      The routing table: match the incoming event,
                          pick groups, pick channels.

Escalation and ack/snooze are deliberately out of scope for v1.
"""
from application import db

# Re-exported for callers that still do
#   `from application.plugins.notify.models import NotificationChannel`
# pylint: disable=unused-import
from application.models.notification_channel import (  # noqa: F401
    NotificationChannel,
    CHANNEL_TYPE_CHOICES,
    register_channel_type,
)
# pylint: enable=unused-import


CONTACT_SOURCE_CHOICES = [
    ('manual',   'Manual (maintained in this UI)'),
    ('imported', 'Imported (CSV / JSON / API)'),
    ('ldap',     'LDAP (looked up dynamically at dispatch)'),
]


class NotifyContact(db.Document):
    """A single recipient."""
    name = db.StringField(required=True, unique=True, max_length=255)
    email = db.StringField()
    phone = db.StringField()
    timezone = db.StringField(default='Europe/Berlin')
    enabled = db.BooleanField(default=True)
    # `ldap:<account>:<search_filter>` — resolved in the LDAP plugin
    # at dispatch time. When present, email/phone above are the
    # fallback if LDAP lookup fails.
    source = db.StringField(choices=CONTACT_SOURCE_CHOICES, default='manual')
    ldap_account = db.StringField()
    ldap_filter = db.StringField()
    # Free-form tags so groups can pull "role=dba" at runtime.
    tags = db.ListField(field=db.StringField())
    # Default delivery channels. On dispatch, the rule's channel list
    # wins if set, else these fire.
    default_channels = db.ListField(
        field=db.ReferenceField(document_type='NotificationChannel'),
    )
    description = db.StringField()

    meta = {'collection': 'notify_contact', 'strict': False,
            'indexes': [{'fields': ['name'], 'unique': True}]}

    def __str__(self):
        return self.name


class NotifyContactGroup(db.Document):
    """A set of contacts addressable by a single name."""
    name = db.StringField(required=True, unique=True, max_length=255)
    description = db.StringField()
    # Static membership.
    members = db.ListField(
        field=db.ReferenceField(document_type='NotifyContact'),
    )
    # Optional dynamic members: match contacts by tag.
    dynamic_tag = db.StringField(
        help_text="Include every contact carrying this tag. Empty = none.",
    )
    # Optional LDAP group — expanded at dispatch time via the LDAP
    # plugin, using <account> with a filter that resolves to a list of
    # mail addresses. One-off contacts are created on the fly with
    # source=ldap so they appear in the dispatch history.
    ldap_account = db.StringField()
    ldap_filter = db.StringField()
    enabled = db.BooleanField(default=True)

    meta = {'collection': 'notify_contact_group', 'strict': False,
            'indexes': [{'fields': ['name'], 'unique': True}]}

    def __str__(self):
        return self.name


class NotifyVacation(db.Document):
    """Route around a contact during their away window."""
    contact = db.ReferenceField(
        document_type='NotifyContact', required=True, reverse_delete_rule=2,
    )
    from_date = db.DateTimeField(required=True)
    to_date = db.DateTimeField(required=True)
    substitute = db.ReferenceField(
        document_type='NotifyContact',
        help_text="Optional: forward dispatches to this contact during "
                  "the away window. Leave blank to drop silently.",
    )
    reason = db.StringField()

    meta = {'collection': 'notify_vacation', 'strict': False,
            'indexes': ['contact', ('contact', '-from_date')]}

    def active_at(self, when):
        """True if `when` falls inside the away window (inclusive)."""
        return self.from_date <= when <= self.to_date

    def __str__(self):
        return f'{self.contact} ({self.from_date:%Y-%m-%d} – {self.to_date:%Y-%m-%d})'


class NotifyShiftCalendar(db.Document):
    """iCal / CalDAV feed resolved to on-call contacts.

    The calendar is polled on a cron interval (see
    `cmdbsyncer notify sync_calendars`); at dispatch time we read the
    cached `active_events` list and pick contacts whose `name` appears
    in the event summary / description. Example event title:
    'On-Call: alice, bob' → NotifyContact(name='alice') and 'bob' are
    on call for the event duration.
    """
    name = db.StringField(required=True, unique=True, max_length=255)
    ical_url = db.StringField(
        required=True,
        help_text="HTTPS URL of the iCal feed (Google public ics, "
                  "Outlook published calendar, CalDAV /.../calendar.ics).",
    )
    # Optional HTTP Basic auth. Username + password are pulled from an
    # Account record — the syncer's authoritative credential store —
    # instead of environment variables, so rotation goes through the
    # existing Accounts UI and the usual audit trail.
    auth_account = db.StringField(
        help_text="Optional: name of an Account whose username + "
                  "password are used for HTTP Basic auth when fetching "
                  "the feed. Leave blank for unauthenticated feeds.",
    )
    timezone = db.StringField(default='Europe/Berlin')
    enabled = db.BooleanField(default=True)
    last_sync_at = db.DateTimeField()
    last_sync_error = db.StringField()
    # Cached snapshot from the last successful sync. One dict per
    # event: {start, end, summary, matched_contact_ids}.
    cached_events = db.ListField(field=db.DictField())
    description = db.StringField()

    meta = {'collection': 'notify_shift_calendar', 'strict': False,
            'indexes': [{'fields': ['name'], 'unique': True}]}

    def __str__(self):
        return self.name


EVENT_SOURCE_CHOICES = [
    ('checkmk',   'Checkmk notification'),
    ('netbox',    'Netbox webhook'),
    ('generic',   'Generic HTTP POST'),
    ('',          '(any)'),
]


class NotifyDispatchRule(db.Document):
    """
    Routing entry.  Evaluated in ascending `sort_field` order.  For
    each event, every matching rule fires unless `last_match=True`.
    """
    name = db.StringField(required=True, unique=True, max_length=255)
    documentation = db.StringField()
    enabled = db.BooleanField(default=True)
    sort_field = db.IntField(default=100)
    last_match = db.BooleanField(default=False)

    # --- Matchers --------------------------------------------------
    # Blank = any. All configured matchers must match.
    source_match = db.StringField(
        choices=EVENT_SOURCE_CHOICES, default='',
        help_text="Event source identifier. Empty matches any source.",
    )
    event_type_match = db.StringField(
        help_text="Regex on the event_type field (e.g. "
                  "`^host\\.(down|unreachable)$`).",
    )
    context_key = db.StringField(
        help_text="Optional: name of a context key to check "
                  "(e.g. `contact_groups`, `host`). Empty = skip.",
    )
    context_value_match = db.StringField(
        help_text="Regex that the context key's value must match.",
    )

    # --- Targets ---------------------------------------------------
    target_groups = db.ListField(
        field=db.ReferenceField(document_type='NotifyContactGroup'),
    )
    # Optional: only the on-call subset from this calendar is alerted.
    # Empty = every group member.
    shift_calendar = db.ReferenceField(
        document_type='NotifyShiftCalendar',
    )
    # Channels to use. Overrides the contact's default_channels when
    # non-empty.
    channels = db.ListField(
        field=db.ReferenceField(document_type='NotificationChannel'),
    )

    meta = {'collection': 'notify_dispatch_rule', 'strict': False,
            'ordering': ['sort_field'],
            'indexes': [{'fields': ['name'], 'unique': True}]}

    def __str__(self):
        return self.name


# NotifyDispatchJob is intentionally NOT a Mongo document: a DB hop
# on every inbound event puts a hard ceiling on throughput and makes
# the endpoint slow when Mongo is busy. See `queue.py` for the RAM
# queue + ring buffer + in-memory job dicts.
