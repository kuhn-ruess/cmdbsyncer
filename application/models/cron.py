"""
Cron Jobs
"""
import hashlib
import hmac
import secrets
from application import db, cron_register


def _generate_webhook_token():
    """Return a fresh URL-safe token *plaintext*. The DB only stores
    the hash (see `_hash_webhook_token`); the plaintext is shown to the
    operator once via the admin UI flash and never persisted."""
    return secrets.token_urlsafe(32)


def _hash_webhook_token(plaintext):
    """SHA-256 hex digest of a webhook-token plaintext.

    Equality-only comparison is sufficient (no replay-protection — that
    is what the enterprise `webhook_signatures` HMAC flow is for), so
    a fast hash is fine. The verifier hashes the submitted token the
    same way and runs `hmac.compare_digest` against the stored digest.
    """
    return hashlib.sha256(plaintext.encode('utf-8')).hexdigest()


# Free-function helpers — keep the actual hash flow out of the
# MongoEngine class machinery so tests can drive it against a plain
# stub without duplicating the logic.

def migrate_legacy_webhook_token(group):
    """Hash the pre-4.1 plaintext token in place if `group` still has
    one. Returns True iff a migration write is needed."""
    if group.webhook_token and not group.webhook_token_hash:
        group.webhook_token_hash = _hash_webhook_token(group.webhook_token)
        group.webhook_token = None
        return True
    return False


def ensure_webhook_token(group):
    """Allocate a webhook token on first enable. Returns the plaintext
    on first allocation (None otherwise). The DB only ever sees the
    SHA-256 hex hash."""
    if not group.webhook_enabled:
        return None
    if group.webhook_token_hash:
        return None
    plaintext = _generate_webhook_token()
    group.webhook_token_hash = _hash_webhook_token(plaintext)
    group.webhook_token = None
    return plaintext


def regenerate_webhook_token(group):
    """Rotate the token. Returns the new plaintext for one-shot display."""
    plaintext = _generate_webhook_token()
    group.webhook_token_hash = _hash_webhook_token(plaintext)
    group.webhook_token = None
    return plaintext


def verify_webhook_token(group, submitted):
    """Constant-time equality between SHA-256 of the submitted plaintext
    and the stored hash."""
    if not submitted or not group.webhook_token_hash:
        return False
    return hmac.compare_digest(
        _hash_webhook_token(submitted),
        group.webhook_token_hash,
    )

intervals = [
    ("10min", "Every 15 minute"), # Crond runs 15min, but the 10 min makes sure it runs everytime
    ("hour", "Every hour"),
    ("daily", "Once Daily"),
]

hours = [
    ('0', '00:00'),
    ('1', '01:00'),
    ('2', '02:00'),
    ('3', '03:00'),
    ('4', '04:00'),
    ('5', '05:00'),
    ('6', '06:00'),
    ('7', '07:00'),
    ('8', '08:00'),
    ('9', '09:00'),
    ('10', '10:00'),
    ('11', '11:00'),
    ('12', '12:00'),
    ('13', '13:00'),
    ('14', '14:00'),
    ('15', '15:00'),
    ('16', '16:00'),
    ('17', '17:00'),
    ('18', '18:00'),
    ('19', '19:00'),
    ('20', '20:00'),
    ('21', '21:00'),
    ('22', '22:00'),
    ('23', '23:00'),
    ('24', '24:00'),
]

class GroupEntry(db.EmbeddedDocument):  # pylint: disable=too-few-public-methods
    """
    Cron Entry
    """
    name = db.StringField(required=True)
    command = db.StringField(choices=cron_register.keys(), required=True)
    account = db.ReferenceField(document_type='Account')


class CronGroup(db.Document):
    """
    Cron Croup
    """

    name = db.StringField(required=True, unique=True)

    interval = db.StringField(choices=intervals)
    custom_interval_in_minutes = db.IntField()
    timerange_from = db.StringField(choices=hours, default='0')
    timerange_to = db.StringField(choices=hours, default='24')
    jobs = db.ListField(field=db.EmbeddedDocumentField(document_type="GroupEntry"))

    render_jobs = db.StringField()

    enabled = db.BooleanField()
    run_once_next = db.BooleanField(default=False)
    continue_on_error = db.BooleanField(default=False)
    webhook_enabled = db.BooleanField(default=False)
    # Plaintext is shown to the operator exactly once after generate /
    # regenerate; the DB only carries the SHA-256 hex digest so a leaked
    # backup or replica does not hand the secret to an attacker.
    webhook_token_hash = db.StringField()
    # Legacy plaintext field — kept around so old documents upgrade
    # transparently. Migrated on read by `migrate_legacy_webhook_token`
    # and never written back.
    webhook_token = db.StringField()
    sort_field = db.IntField(default=0)

    # Set by features that auto-manage their own CronGroup (e.g. scheduled
    # backups). Protected groups can be enabled/disabled and edited but
    # not deleted from the UI — deleting the owning record removes them.
    protected = db.BooleanField(default=False)

    meta = {
        'strict': False,
    }

    def migrate_legacy_webhook_token(self):
        """See module-level `migrate_legacy_webhook_token`."""
        return migrate_legacy_webhook_token(self)

    def ensure_webhook_token(self):
        """See module-level `ensure_webhook_token`."""
        return ensure_webhook_token(self)

    def regenerate_webhook_token(self):
        """See module-level `regenerate_webhook_token`."""
        return regenerate_webhook_token(self)

    def verify_webhook_token(self, submitted):
        """See module-level `verify_webhook_token`."""
        return verify_webhook_token(self, submitted)


commands = [
    ('cmk-export_hosts', "Checkmk: Export Hosts"),
    ('cmk-export_groups', "Checkmk: Export Groups"),
    ('cmk-export_rules', "Checkmk: Export Rules"),
    ('ansible-manage_hosts', "Ansible: Manage Hosts"),
    ('ansible-manage_servers', "Ansible: Manage Servers"),
    ('ansible-fire_playbook_rules', "Ansible: Fire Playbook Rules"),
]

class CronStats(db.Document):
    """
    Cron Stats
    """

    group = db.StringField()
    next_run = db.DateTimeField()

    last_start = db.DateTimeField()
    is_running = db.BooleanField(default=False)
    last_ended = db.DateTimeField()
    last_success_at = db.DateTimeField()
    failure = db.BooleanField(default=False)

    pid = db.IntField()

    last_message = db.StringField()

    all_messages = db.StringField()


    meta = {
        'strict' : False
    }
