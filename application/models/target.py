"""
Target
"""
# pylint: disable=no-member
from application import db


class Target(db.Document):
    """
    Target
    """


    name = db.StringField(required=True, unique=True)
    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }
