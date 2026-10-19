"""
Secret Store

One store for every secret the syncer keeps: passwords, tokens and
certificates. It started out as the Checkmk password store and still lives
in that collection (``checkmk_password``), so every existing entry keeps its
ObjectId and with it the Checkmk password ident ``cmdbsyncer_<id>`` the
password export writes. No data is copied or migrated.

An entry is either global (no host) or bound to one host. A host-bound
entry is found by ``(host, key)``, which is how an import stores the secret
fields of a row and how ``{{ secret('key') }}`` resolves it for the host a
rule is rendered for. When the host is gone or archived the entry is marked
orphaned and kept, so it can be bound to another host later.
"""
# pylint: disable=too-few-public-methods,too-many-instance-attributes,no-member
import datetime

from cryptography.fernet import Fernet
from application import db, app

SECRET_KINDS = (
    ('password', 'Password'),
    ('token', 'Token'),
    ('certificate', 'Certificate'),
)

# Kinds Checkmk can hold in its password store. A certificate cannot be
# created there over the REST API, so it is copied by hand instead.
CHECKMK_EXPORTABLE_KINDS = ('password', 'token')


def host_secret_name(hostname, key):
    """Name of the entry holding secret ``key`` of host ``hostname``."""
    return f"{hostname}:{key}"


class Secret(db.Document):
    """
    Entry of the Secret Store
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    title = db.StringField(required=True)
    comment = db.StringField()
    documentation_url = db.StringField()
    password_crypted = db.StringField()
    owner = db.StringField(default="admin", required=True)
    shared = db.ListField(field=db.StringField())
    last_export_hash = db.StringField()

    # Host binding. Stored as id plus name instead of a ReferenceField: a
    # deleted host must leave a readable, orphaned entry behind, not a
    # reference that fails to dereference.
    host_id = db.ObjectIdField()
    hostname = db.StringField()
    key = db.StringField()
    kind = db.StringField(choices=SECRET_KINDS, default='password')
    # Entries written before this field existed carry nothing and keep
    # being exported, so the query uses ``export_to_checkmk__ne=False``.
    export_to_checkmk = db.BooleanField(default=True)
    orphaned = db.BooleanField(default=False)
    source = db.StringField()
    updated_at = db.DateTimeField()

    enabled = db.BooleanField()

    meta = {
        'collection': 'checkmk_password',
        'strict': False,
        'indexes': [
            'host_id',
            ('host_id', 'key'),
        ],
    }

    def set_password(self, password):
        """
        Encryp Password
        """
        f = Fernet(app.config['CRYPTOGRAPHY_KEY'])
        self.password_crypted = f.encrypt(str.encode(password)).decode('utf-8')

    def get_password(self):
        """
        Decrypt Password
        """
        f = Fernet(app.config['CRYPTOGRAPHY_KEY'])
        return f.decrypt(str.encode(self.password_crypted)).decode('utf-8')

    # A plain method, not a property: the admin view's save hook writes
    # every string attribute back, and a property has no setter.
    def checkmk_ident(self):
        """Ident of this entry in the Checkmk password store."""
        return f"cmdbsyncer_{self.id}"

    def get_host(self):
        """The bound host, or None when global or the host is gone."""
        if self.host_id is None:
            return None
        from application.models.host import Host  # pylint: disable=import-outside-toplevel
        return Host.objects(id=self.host_id).first()

    def bind_to_host(self, host):
        """
        Bind this entry to ``host`` (and clear the orphaned flag). The
        caller checks the user may do so and saves.
        """
        self.host_id = host.id
        self.hostname = host.hostname
        if self.key:
            self.name = host_secret_name(host.hostname, self.key)
        self.orphaned = False

    def __str__(self):
        return self.name or ''


def find_host_secret(hostname, key):
    """The entry bound to the host named ``hostname`` under ``key``."""
    if not hostname or not key:
        return None
    from application.models.host import Host  # pylint: disable=import-outside-toplevel
    host = Host.objects(hostname=hostname).only('id').first()
    if not host:
        return None
    return Secret.objects(host_id=host.id, key=key, orphaned__ne=True).first()


def find_global_secret(name):
    """The global (not host-bound) entry called ``name``."""
    if not name:
        return None
    return Secret.objects(name=name, host_id=None).first()


def store_host_secret(host, key, value, source, kind=None):
    """
    Create or update the entry holding secret ``key`` of ``host``.

    The kind defaults to ``certificate`` for a PEM block and ``password``
    otherwise; only the latter is exported to Checkmk. Returns the entry.
    """
    entry = Secret.objects(host_id=host.id, key=key).first()
    if entry is None:
        entry = Secret(host_id=host.id, key=key)
        entry.kind = kind or ('certificate' if 'BEGIN CERTIFICATE' in value
                              else 'password')
        entry.export_to_checkmk = entry.kind in CHECKMK_EXPORTABLE_KINDS
        entry.enabled = True
    elif kind:
        entry.kind = kind
    entry.hostname = host.hostname
    entry.name = host_secret_name(host.hostname, key)
    entry.title = entry.title or f"{host.hostname} {key}"
    entry.orphaned = False
    entry.source = source
    entry.updated_at = datetime.datetime.utcnow()
    entry.set_password(value)
    entry.save()
    return entry


def refresh_orphans():
    """
    Flag host-bound entries whose host is gone or archived as orphaned,
    and clear the flag again when the host is back. Nothing is deleted.
    Returns the number of entries whose flag changed.
    """
    from application.models.host import Host  # pylint: disable=import-outside-toplevel
    bound = Secret.objects(host_id__ne=None).only('id', 'host_id', 'orphaned')
    host_ids = {entry.host_id for entry in bound}
    alive = set(Host.objects(id__in=list(host_ids), deleted_at=None).scalar('id'))
    changed = 0
    for entry in bound:
        orphaned = entry.host_id not in alive
        if bool(entry.orphaned) != orphaned:
            Secret.objects(id=entry.id).update_one(set__orphaned=orphaned)
            changed += 1
    return changed


def resolve_secret(hostname, key):
    """
    The entry ``secret('key')`` means for the host ``hostname``: the one
    bound to that host, else the global entry called ``key``.
    """
    entry = find_host_secret(hostname, key) if hostname else None
    return entry or find_global_secret(key)
