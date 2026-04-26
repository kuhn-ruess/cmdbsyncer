"""
Internal User Accounts
"""
# pylint: disable=no-member  # mongoengine document fields (id, objects, ...) are dynamic
import uuid
from datetime import datetime, timedelta
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from joserfc import jwt
from joserfc.jwk import OctKey
from application import db

roles = [
  ('host', "Hosts"),
  ('objects', "Objects"),
  ('account', "Account Management"),
  ('log', "Log View"),
  ('global_attributes', "Global Attributes"),
  ('fileadmin', "File Management"),
  ('user', "User Management"),
  ('ansible', "Ansible"),
  ('checkmk', "Checkmk"),
  ('i-doit', "I-Doit"),
  ('netbox', "Netbox"),
  ('vmware', "VMware"),
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

    def generate_token(self, purpose, expiration=60):
        """
        Token generator. `purpose` binds the token to a specific action
        (e.g. "pw_reset") so it cannot be replayed in a different context.
        """
        now = datetime.now()
        exp = now + timedelta(minutes=expiration)
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
            'iat': int(now.timestamp()),
            'exp': int(exp.timestamp()),
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
