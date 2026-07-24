"""
Internal User Accounts
"""
# pylint: disable=no-member  # mongoengine document fields (id, objects, ...) are dynamic
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from joserfc import jwt
from joserfc.jwk import OctKey
from application import db


# Personal API tokens are shown to the user once and only stored hashed —
# same approach as the CronGroup webhook tokens. The prefix makes a token
# recognisable in code/logs and lets the API auth cheaply tell a token
# apart from a Basic-auth password without hashing arbitrary input.
API_TOKEN_PREFIX = 'cmdb_pat_'


def _hash_api_token(plaintext):
    """SHA-256 hex digest of an API-token plaintext (equality check only)."""
    return hashlib.sha256(plaintext.encode('utf-8')).hexdigest()

roles = [
  ('host', "Hosts"),
  ('objects', "Objects"),
  ('hard_delete', "Permanently delete archived objects"),
  ('approval', "Approve or reject pending critical-label changes"),
  ('approval_bypass', "Skip the approval queue when editing critical labels"),
  ('account', "Account Management"),
  ('project', "Projects"),
  ('cron', "Cron Groups & Status"),
  ('log', "Log View"),
  ('global_attributes', "Global Attributes"),
  ('rule', "Generic Rules (Filter, Rewrite, Custom Attributes)"),
  ('fileadmin', "File Management"),
  ('user', "User Management"),
  ('ansible', "Ansible"),
  ('checkmk', "Checkmk"),
  ('i-doit', "I-Doit"),
  ('netbox', "Netbox"),
  ('vmware', "VMware"),
  ('jira', "Jira"),
]

api_roles = [
  ('all', "Full rights"),
  ('ansible', "Ansible"),
  ('mcp', "MCP server (stdio + SSE)"),
  ('objects', "Objects"),
  ('rules', "Rule import/export and autorules"),
  ('syncer', "Syncer"),
  ('metrics', "Prometheus metrics scrape"),
]

class ApiToken(db.EmbeddedDocument):  # pylint: disable=too-few-public-methods
    """
    A personal API access token belonging to a User. Only the hash is
    stored; the plaintext is shown once on creation. Tokens authenticate
    as their owner and therefore carry exactly the owner's api_roles and
    account scope.
    """
    # Public identifier used to display/revoke the token — never secret.
    token_id = db.StringField(required=True)
    token_hash = db.StringField(required=True)
    label = db.StringField(max_length=120)
    # First characters of the plaintext, kept so the user can recognise a
    # token in the list without exposing the secret.
    prefix = db.StringField()
    created_at = db.DateTimeField()
    last_used_at = db.DateTimeField()
    # Optional — a token without an expiry never expires on its own.
    expires_at = db.DateTimeField()

    def is_expired(self):
        """True if the token carries an expiry that has passed."""
        return bool(self.expires_at and self.expires_at < datetime.utcnow())


class User(db.Document, UserMixin):
    """
    User for login
    """

    email = db.EmailField(unique=True, required=True)
    pwdhash = db.StringField()
    #name = db.StringField(unique=True, required=True)
    name = db.StringField(required=True)
    global_admin = db.BooleanField(default=False)
    roles = db.ListField(field=db.StringField(choices=roles))
    api_roles = db.ListField(field=db.StringField(choices=api_roles, default="all"))

    # Optional account allowlist limiting what this user may see and touch.
    # Empty = unrestricted (everything, as before). When set it applies to
    # BOTH the REST API (every host-facing call is limited to hosts of these
    # accounts — create/update may only name them, lists/bulk only return
    # them, delete only reaches them) AND the web UI Host and Objects lists.
    restrict_to_accounts = db.ListField(field=db.StringField())

    # Personal API access tokens (hashed). See ApiToken.
    api_tokens = db.ListField(field=db.EmbeddedDocumentField(document_type='ApiToken'))

    theme = db.StringField(default='default')

    tfa_secret = db.StringField()

    disabled = db.BooleanField(default=False)

    date_added = db.DateTimeField()
    date_changed = db.DateTimeField(default=datetime.now())
    date_password = db.DateTimeField()
    last_login = db.DateTimeField()
    force_password_change = db.BooleanField(default=False)

    meta = {'indexes': [
        'email'
        ],
    'strict': False,
    }


    def set_password(self, password):
        """
        Password seter
        """
        self.date_password = datetime.now()
        self.pwdhash = generate_password_hash(password)

    def check_password(self, password):
        """
        Password checker
        """
        return check_password_hash(self.pwdhash, password)

    def account_scope(self):
        """
        Account-name allowlist limiting what this user may see and touch,
        or ``None`` when the user is unrestricted. Shared by the REST API
        and the web-UI Host/Objects lists so both honour the same rule.
        """
        accounts = {name for name in (self.restrict_to_accounts or []) if name}
        return accounts or None

    def create_api_token(self, label=None, expires_at=None):
        """
        Generate a new personal API token, append it (hashed) to the user
        and return the one-time plaintext. The caller must ``save()``.
        """
        plaintext = f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
        self.api_tokens.append(ApiToken(
            token_id=uuid.uuid4().hex,
            token_hash=_hash_api_token(plaintext),
            label=(label or '').strip()[:120] or 'API token',
            prefix=plaintext[:len(API_TOKEN_PREFIX) + 6],
            created_at=datetime.utcnow(),
            expires_at=expires_at,
        ))
        return plaintext

    def revoke_api_token(self, token_id):
        """
        Drop the token with the given public ``token_id``. Returns True if
        a token was removed. The caller must ``save()``.
        """
        remaining = [t for t in self.api_tokens if t.token_id != token_id]
        if len(remaining) == len(self.api_tokens):
            return False
        self.api_tokens = remaining
        return True

    def generate_token(self, purpose, expiration=60):
        """
        Token generator. `purpose` binds the token to a specific action
        (e.g. "pw_reset") so it cannot be replayed in a different context.
        Epochs use `time.time()` so iat/exp are UTC and the validator's
        clock comparison stays correct on non-UTC hosts.
        """
        now_epoch = time.time()
        pwd_iat = int(self.date_password.timestamp()) if self.date_password else 0
        header = {
              'alg': 'HS256'
        }
        key = OctKey.import_key(current_app.config['SECRET_KEY'])
        data = {
            'userid': str(self.id),
            'purpose': purpose,
            'pwd_iat': pwd_iat,
            'jti': uuid.uuid4().hex,
            'iat': int(now_epoch),
            'exp': int(now_epoch + expiration * 60),
        }

        return jwt.encode(header, data, key)


    def is_admin(self):
        """
        Check Admin Status
        """
        return self.global_admin

    def has_right(self, role):
        """
        Grand User the right if he has the role
        or is global admin
        """
        if role in self.roles:
            return True
        if self.global_admin:
            return True
        return False

    def get_id(self):
        """ User Mixin overwrite """
        return str(self.id)

    def __str__(self):
        """
        Model representation
        """
        return "User "+ self.email

    @staticmethod
    def migrate_missing_names():
        """
        Migration helper to set a default name for users missing it or with duplicate names.
        Call this once after deployment.
        """
        # Set missing names
        try:
            User._get_collection().drop_index('name_1')
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        users = User.objects()
        found_names = []
        for idx, user in enumerate(users):
            if not user.name:
                user.name = user.email
                user.save()
            else:
                if user.name in found_names:
                    user.name += f"-{idx}"
                    user.save()
                    continue
            found_names.append(user.name)


def find_user_by_api_token(plaintext):
    """
    Resolve a personal API token plaintext to its owner.

    Returns ``(user, token)`` for a valid, non-expired token on an enabled
    user, otherwise ``(None, None)``. The lookup is an exact hash match, so
    a single indexed query finds the token without scanning every user.
    """
    if not plaintext or not plaintext.startswith(API_TOKEN_PREFIX):
        return None, None
    token_hash = _hash_api_token(plaintext)
    # pylint: disable=no-member
    user = User.objects(disabled__ne=True,
                        api_tokens__token_hash=token_hash).first()
    if not user:
        return None, None
    for token in user.api_tokens:
        if hmac.compare_digest(token.token_hash, token_hash):
            if token.is_expired():
                return None, None
            return user, token
    return None, None
