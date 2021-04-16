"""
Source
"""
# pylint: disable=no-member
from application import db


class Source(db.Document):
    """
    Source
    """


    name = db.StringField(required=True, unique=True)

    address = db.StringField()
    username = db.StringField()
    password = db.StringField()


    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }
