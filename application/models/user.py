"""
Internal User Accounts
"""
from datetime import datetime, timedelta
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.jose import jwt
from application import db

roles = [
  ('host', "Hosts"),
  ('objects', "Objects"),
  ('account', "Account Management"),
  ('log', "Log View"),
  ('global_attributes', "Global Attributes"),
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
  ('objects', "Objects"),
  ('syncer', "Syncer"),
]

class User(db.Document, UserMixin):
    """
    User for login
    """

    email = db.EmailField(unique=True, required=True)
    pwdhash = db.StringField()
    name = db.StringField(unique=True, required=True)
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

    def generate_token(self, expiration=3600):
        """
        Token generator
        """
        dt = datetime.now()+timedelta(minutes=expiration)
        header = {
              'alg': 'HS256'
        }
        key = current_app.config['SECRET_KEY']
        data = {
            'userid': str(self.id),
            'exp' : dt
        }

        return jwt.encode(header=header, payload=data, key=key)


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