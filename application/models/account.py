"""
Account
"""
from application import db

account_types = [
    ('cmkv1', "Checkmk Version 1.x"),
    ('cmkv2', "Checkmk Version 2.x"),
    ('csv', "CSV File"),
    ('json', "Json File"),
    ('mysql', "Mysql Table"),
    ('netbox', "Netbox Account"),
    ('cisco_dna', "Cisco DNA Account"),
    ('restapi', "Internal Rest API Credentials"),
    ('external_restapi', "Remote Rest API"),
    ('maintenance', "Maintanence Jobs"),
    ('custom', "Custom Entries, like DBs"),
]


class CustomEntry(db.EmbeddedDocument):
    """
    Custom Attributes for Setup
    """
    name = db.StringField()
    value = db.StringField()

class Account(db.Document):
    """
    Account
    """

    name = db.StringField(required=True, unique=True)
    typ = db.StringField(choices=account_types)
    is_master = db.BooleanField(default=False)

    address = db.StringField()
    username = db.StringField()
    password = db.StringField()

    custom_fields = db.ListField(db.EmbeddedDocumentField(CustomEntry))


    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }


    def __str__(self):
        return f"{self.name} ({self.typ})"
