"""
Internal User Accounts
"""
from datetime import datetime
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from application import db

roles = [
  ('rule', "Rule Management"),
  ('host', "Host Management"),
  ('account', "Account Management"),
  ('user', "User Management"),
]

class User(db.Document, UserMixin):
    """
    User for login
    """

    email = db.EmailField(unique=True, required=True)
    pwdhash = db.StringField()
    name = db.StringField()
    global_admin = db.BooleanField(default=False)
    roles = db.ListField(db.StringField(choices=roles))

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

    def generate_token(self, expiration=3600, custom_values=False):
        """
        Token generator
        """
        token_data = {'userid': str(self.id)}
        if custom_values:
            token_data.update(custom_values)
        ser = Serializer(current_app.config['SECRET_KEY'], expiration)
        return ser.dumps(token_data)

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
