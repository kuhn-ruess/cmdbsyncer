"""
Account
"""
# pylint: disable=no-member
from application import db

account_types = [
    ('cmkv1', "Checkmk Version 1.x"),
    ('cmkv2', "Checkmk Version 2.x"),
    ('database', "Database"),
    ('restapi', "Rest API"),
]

class Account(db.Document):
    """
    Account
    """


    name = db.StringField(required=True, unique=True)
    typ = db.StringField(choices=account_types)

    address = db.StringField()
    username = db.StringField()
    password = db.StringField()

    database = db.StringField()
    port = db.IntField()


    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }
